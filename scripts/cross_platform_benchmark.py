#!/usr/bin/env python3

"""
Cross-platform benchmark comparison tool for SeBS.
Runs benchmarks across multiple languages and cloud platforms,
aggregates results, and provides comparison analysis.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import subprocess
import traceback

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
sys.path.insert(0, PROJECT_ROOT)

# Language-version mappings for different platforms
LANGUAGE_CONFIGS = {
    'aws': {
        'python': ['3.11', '3.10', '3.9', '3.8'],
        'nodejs': ['16'],
        'rust': ['1.80', '1.81', '1.82'],
        'java': ['17'],
        'pypy': ['3.11']
    },
    'azure': {
        'python': ['3.11', '3.10', '3.9', '3.8'],
        'nodejs': ['20', '18', '16'],
        'java': ['17'],
        'pypy': ['3.11']
    },
    'gcp': {
        'python': ['3.12', '3.11', '3.10', '3.9', '3.8'],
        'nodejs': ['20', '18']
    },
    'local': {
        'python': ['3.11', '3.10', '3.9'],
        'nodejs': ['20', '18', '16'],
        'pypy': ['3.11']
    }
}

class BenchmarkRunner:
    """Orchestrates benchmark execution across platforms and languages."""
    
    def __init__(self, output_dir: str, cache_dir: str = 'cache', verbose: bool = False, container_deployment_for: Optional[List[str]] = None):
        self.output_dir = Path(output_dir).resolve()
        self.cache_dir = cache_dir
        self.verbose = verbose
        self.container_deployment_for = set(container_deployment_for or [])
        self.results = {
            'metadata': {
                'start_time': datetime.now().isoformat(),
                'end_time': None,
                'version': '1.0.0'
            },
            'benchmarks': {}
        }
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        log_file = self.output_dir / 'benchmark_run.log'
        logging.basicConfig(
            level=logging.DEBUG if verbose else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def run_single_benchmark(
        self,
        benchmark: str,
        platform: str,
        language: str,
        version: str,
        config_file: str,
        input_size: str = 'test',
        repetitions: int = 5,
        memory: int = 256,
        architecture: str = 'x64',
        container_deployment: bool = False
    ) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Run a single benchmark configuration.
        
        Returns:
            (success, output_file, error_message)
        """
        run_id = f"{benchmark}_{platform}_{language}_{version}_{memory}MB"
        
        # Determine deployment type for logging
        should_use_container = (
            container_deployment or 
            platform in self.container_deployment_for or
            ((platform == 'aws' or platform == 'gcp') and language == 'pypy')
        )
        deployment_type = "container" if should_use_container else "package"
        
        self.logger.info(f"Starting: {run_id} (deployment: {deployment_type})")
        
        # Create experiment output directory (use absolute path)
        experiment_dir = (self.output_dir / run_id).resolve()
        experiment_dir.mkdir(parents=True, exist_ok=True)
        
        # Update config for this run
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            # Update configuration
            config['experiments']['runtime'] = {
                'language': language,
                'version': version
            }
            config['experiments']['repetitions'] = repetitions
            config['experiments']['memory'] = memory
            config['experiments']['architecture'] = architecture
            config['deployment']['name'] = platform
            
            # Write updated config
            run_config_file = experiment_dir / 'config.json'
            with open(run_config_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Construct sebs.py command
            cmd = [
                sys.executable,
                os.path.join(PROJECT_ROOT, 'sebs.py'),
                'benchmark',
                'invoke',
                benchmark,
                input_size,
                '--config', str(run_config_file),
                '--deployment', platform,
                '--language', language,
                '--language-version', version,
                '--memory', str(memory),
                '--architecture', architecture,
                '--output-dir', str(experiment_dir),
                '--cache', self.cache_dir
            ]
            
            # Add --container-deployment if requested or required
            # Priority: explicit flag > per-platform setting > automatic for PyPy on AWS/GCP
            should_use_container = (
                container_deployment or 
                platform in self.container_deployment_for or
                ((platform == 'aws' or platform == 'gcp') and language == 'pypy')
            )
            if should_use_container:
                cmd.append('--container-deployment')
            
            if self.verbose:
                cmd.append('--verbose')
            
            self.logger.debug(f"Command: {' '.join(cmd)}")
            
            # Execute benchmark (run from project root for proper path resolution)
            start_time = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
                cwd=PROJECT_ROOT  # Run from project root
            )
            execution_time = time.time() - start_time
            
            # Ensure the directory still exists (sebs.py might have cleaned it up on error)
            experiment_dir.mkdir(parents=True, exist_ok=True)
            
            # Save stdout/stderr
            with open(experiment_dir / 'stdout.log', 'w') as f:
                f.write(result.stdout)
            with open(experiment_dir / 'stderr.log', 'w') as f:
                f.write(result.stderr)
            
            if result.returncode == 0:
                self.logger.info(f"✓ Completed: {run_id} ({execution_time:.2f}s)")
                
                # Look for experiments.json in the output
                exp_json = experiment_dir / 'experiments.json'
                if not exp_json.exists():
                    # Try to find it in subdirectories
                    exp_files = list(experiment_dir.glob('**/experiments.json'))
                    if exp_files:
                        exp_json = exp_files[0]
                
                return True, str(experiment_dir), None
            else:
                error_msg = f"Failed with return code {result.returncode}"
                self.logger.error(f"✗ Failed: {run_id} - {error_msg}")
                self.logger.debug(f"Stderr: {result.stderr[:500]}")
                return False, str(experiment_dir), error_msg
                
        except subprocess.TimeoutExpired:
            error_msg = "Benchmark execution timed out"
            self.logger.error(f"✗ Timeout: {run_id}")
            return False, str(experiment_dir), error_msg
        except Exception as e:
            error_msg = f"Exception: {str(e)}"
            self.logger.error(f"✗ Error: {run_id} - {error_msg}")
            self.logger.debug(traceback.format_exc())
            return False, str(experiment_dir), error_msg
    
    def run_comparison(
        self,
        benchmarks: List[str],
        platforms: List[str],
        languages: List[str],
        config_file: str,
        input_size: str = 'test',
        repetitions: int = 5,
        memory_sizes: List[int] = [256],
        architecture: str = 'x64',
        versions: Optional[Dict[str, List[str]]] = None,
        container_deployment: bool = False
    ):
        """
        Run benchmarks across multiple configurations.
        
        Args:
            benchmarks: List of benchmark names (e.g., ['010.sleep', '110.dynamic-html'])
            platforms: List of platforms (e.g., ['aws', 'azure'])
            languages: List of languages (e.g., ['python', 'nodejs'])
            config_file: Path to base configuration file
            input_size: Benchmark input size
            repetitions: Number of repetitions per benchmark
            memory_sizes: List of memory configurations to test
            architecture: Target architecture (x64 or arm64)
            versions: Optional dict mapping language to specific versions
        """
        total_runs = 0
        successful_runs = 0
        failed_runs = 0
        
        for benchmark in benchmarks:
            self.results['benchmarks'][benchmark] = {}
            
            for platform in platforms:
                self.results['benchmarks'][benchmark][platform] = {}
                
                for language in languages:
                    # Check if language is supported on this platform
                    if language not in LANGUAGE_CONFIGS.get(platform, {}):
                        self.logger.warning(f"Skipping {language} on {platform} (not supported)")
                        continue
                    
                    # Get versions to test
                    if versions and language in versions:
                        lang_versions = versions[language]
                    else:
                        # Use first available version by default
                        lang_versions = [LANGUAGE_CONFIGS[platform][language][0]]
                    
                    self.results['benchmarks'][benchmark][platform][language] = {}
                    
                    for version in lang_versions:
                        # Verify version is supported
                        if version not in LANGUAGE_CONFIGS[platform][language]:
                            self.logger.warning(
                                f"Skipping {language} {version} on {platform} (version not supported)"
                            )
                            continue
                        
                        self.results['benchmarks'][benchmark][platform][language][version] = {}
                        
                        for memory in memory_sizes:
                            total_runs += 1
                            
                            success, output_dir, error = self.run_single_benchmark(
                                benchmark=benchmark,
                                platform=platform,
                                language=language,
                                version=version,
                                config_file=config_file,
                                input_size=input_size,
                                repetitions=repetitions,
                                memory=memory,
                                architecture=architecture,
                                container_deployment=container_deployment
                            )
                            
                            result_entry = {
                                'success': success,
                                'output_directory': output_dir,
                                'memory_mb': memory,
                                'architecture': architecture,
                                'repetitions': repetitions,
                                'input_size': input_size
                            }
                            
                            if success:
                                successful_runs += 1
                                # Try to extract metrics and full experiment data
                                try:
                                    extracted = self._extract_metrics(output_dir)
                                    
                                    # Store full experiments.json data if available
                                    if 'full_experiment_data' in extracted:
                                        result_entry['experiment_data'] = extracted['full_experiment_data']
                                        # Also store summary metrics
                                        result_entry['metrics'] = {
                                            k: v for k, v in extracted.items() 
                                            if k != 'full_experiment_data'
                                        }
                                    else:
                                        result_entry['metrics'] = extracted
                                except Exception as e:
                                    self.logger.warning(f"Could not extract metrics: {e}")
                            else:
                                failed_runs += 1
                                result_entry['error'] = error
                            
                            self.results['benchmarks'][benchmark][platform][language][version][f'{memory}MB'] = result_entry
        
        # Update end time and summary
        self.results['metadata']['end_time'] = datetime.now().isoformat()
        self.results['metadata']['summary'] = {
            'total_runs': total_runs,
            'successful': successful_runs,
            'failed': failed_runs,
            'success_rate': f"{(successful_runs/total_runs*100):.1f}%" if total_runs > 0 else "N/A"
        }
        
        # Save results
        output_file = self.output_dir / 'comparison_results.json'
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"Benchmark Comparison Complete!")
        self.logger.info(f"{'='*60}")
        self.logger.info(f"Total runs: {total_runs}")
        self.logger.info(f"Successful: {successful_runs}")
        self.logger.info(f"Failed: {failed_runs}")
        self.logger.info(f"Results saved to: {output_file}")
        
        return self.results
    
    def _extract_metrics(self, output_dir: str) -> Dict:
        """Extract key metrics from experiment output and preserve full experiments.json data."""
        metrics = {}
        
        # Look for experiments.json
        exp_json_paths = [
            Path(output_dir) / 'experiments.json',
            *Path(output_dir).glob('**/experiments.json')
        ]
        
        for exp_json in exp_json_paths:
            if exp_json.exists():
                with open(exp_json, 'r') as f:
                    data = json.load(f)
                
                # Store the full experiments.json data
                metrics['full_experiment_data'] = data
                
                # Extract timing information from invocations for summary
                if '_invocations' in data:
                    invocations = data['_invocations']
                    
                    for func_name, func_data in invocations.items():
                        execution_times = []
                        cold_starts = 0
                        warm_starts = 0
                        
                        for inv_id, inv_data in func_data.items():
                            if 'times' in inv_data:
                                if 'client' in inv_data['times']:
                                    # Client time is in microseconds, convert to ms
                                    execution_times.append(inv_data['times']['client'] / 1000)
                            
                            if 'stats' in inv_data:
                                if inv_data['stats'].get('cold_start'):
                                    cold_starts += 1
                                else:
                                    warm_starts += 1
                        
                        if execution_times:
                            metrics['execution_times_ms'] = execution_times
                            metrics['avg_execution_time_ms'] = sum(execution_times) / len(execution_times)
                            metrics['min_execution_time_ms'] = min(execution_times)
                            metrics['max_execution_time_ms'] = max(execution_times)
                            metrics['cold_starts'] = cold_starts
                            metrics['warm_starts'] = warm_starts
                
                break
        
        return metrics


def main():
    parser = argparse.ArgumentParser(
        description='Run cross-platform benchmark comparisons',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare Python and Node.js on AWS and Azure (with auto-plotting)
  %(prog)s --benchmarks 010.sleep 110.dynamic-html \\
           --platforms aws azure \\
           --languages python nodejs \\
           --config config/example.json \\
           --output results/comparison_$(date +%%Y%%m%%d) \\
           --plot

  # Compare AWS (container) vs Azure (package deployment)
  %(prog)s --benchmarks 010.sleep \\
           --platforms aws azure \\
           --languages python \\
           --container-deployment-for aws \\
           --config config/example.json \\
           --output results/aws_container_vs_azure_package \\
           --plot

  # Compare specific Python versions on AWS
  %(prog)s --benchmarks 501.graph-pagerank \\
           --platforms aws \\
           --languages python \\
           --python-versions 3.11 3.10 3.9 \\
           --memory 512 1024 \\
           --config config/example.json \\
           --plot
        """
    )
    
    parser.add_argument('--benchmarks', nargs='+', required=True,
                        help='Benchmark names to run (e.g., 010.sleep 110.dynamic-html)')
    parser.add_argument('--platforms', nargs='+', required=True,
                        choices=['aws', 'azure', 'gcp', 'local'],
                        help='Platforms to test on')
    parser.add_argument('--languages', nargs='+', required=True,
                        help='Languages to test (e.g., python nodejs rust java)')
    parser.add_argument('--config', required=True,
                        help='Base configuration file')
    parser.add_argument('--output', required=True,
                        help='Output directory for results')
    
    # Optional parameters
    parser.add_argument('--input-size', default='test',
                        choices=['test', 'small', 'large'],
                        help='Benchmark input size (default: test)')
    parser.add_argument('--repetitions', type=int, default=5,
                        help='Number of repetitions per benchmark (default: 5)')
    parser.add_argument('--memory', nargs='+', type=int, default=[256],
                        help='Memory sizes in MB to test (default: 256)')
    parser.add_argument('--architecture', default='x64',
                        choices=['x64', 'arm64'],
                        help='Target architecture (default: x64)')
    parser.add_argument('--cache', default='cache',
                        help='Cache directory (default: cache)')
    
    # Language-specific version overrides
    parser.add_argument('--python-versions', nargs='+',
                        help='Specific Python versions to test')
    parser.add_argument('--nodejs-versions', nargs='+',
                        help='Specific Node.js versions to test')
    parser.add_argument('--rust-versions', nargs='+',
                        help='Specific Rust versions to test')
    parser.add_argument('--java-versions', nargs='+',
                        help='Specific Java versions to test')
    
    parser.add_argument('--verbose', action='store_true',
                        help='Enable verbose output')

    parser.add_argument('--container-deployment', action='store_true',
                        help='Run functions as containers (all platforms)')
    parser.add_argument('--container-deployment-for', nargs='+',
                        help='Specific platforms to use container deployment (e.g., aws gcp)')
    
    parser.add_argument('--plot', action='store_true',
                        help='Automatically generate plots after benchmarking')
    
    args = parser.parse_args()
    
    # Build version overrides
    versions = {}
    if args.python_versions:
        versions['python'] = args.python_versions
    if args.nodejs_versions:
        versions['nodejs'] = args.nodejs_versions
    if args.rust_versions:
        versions['rust'] = args.rust_versions
    if args.java_versions:
        versions['java'] = args.java_versions
    
    # Create runner
    runner = BenchmarkRunner(
        output_dir=args.output,
        cache_dir=args.cache,
        verbose=args.verbose,
        container_deployment_for=args.container_deployment_for
    )
    
    # Run comparison
    try:
        results = runner.run_comparison(
            benchmarks=args.benchmarks,
            platforms=args.platforms,
            languages=args.languages,
            config_file=args.config,
            input_size=args.input_size,
            repetitions=args.repetitions,
            memory_sizes=args.memory,
            architecture=args.architecture,
            versions=versions if versions else None,
            container_deployment=args.container_deployment
        )
        
        print("\n" + "="*60)
        print("✓ Benchmark comparison completed successfully!")
        print("="*60)
        print(f"Results: {args.output}/comparison_results.json")
        print(f"Logs: {args.output}/benchmark_run.log")
        
        # Auto-generate plots if requested
        if args.plot:
            print("\n" + "="*60)
            print("Generating plots...")
            print("="*60)
            try:
                # Suppress matplotlib debug output
                logging.getLogger('matplotlib').setLevel(logging.WARNING)
                logging.getLogger('PIL').setLevel(logging.WARNING)
                
                from plot_comparison import BenchmarkVisualizer
                results_file = f"{args.output}/comparison_results.json"
                visualizer = BenchmarkVisualizer(results_file)
                visualizer.create_all_plots()
                print(f"\n✓ Plots saved to: {visualizer.output_dir}")
            except Exception as e:
                print(f"Warning: Failed to generate plots: {e}")
                print("You can generate plots manually with:")
                print(f"  python scripts/plot_comparison.py {args.output}/comparison_results.json")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user")
        return 130
    except Exception as e:
        print(f"\n\nError during benchmark execution: {e}")
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

