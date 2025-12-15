#!/usr/bin/env python3

"""
Visualization tool for cross-platform benchmark comparisons.
Creates publication-quality plots comparing performance across
languages, platforms, and configurations.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import seaborn as sns

# Set style
sns.set_style("whitegrid")
sns.set_context("paper", font_scale=1.2)

# Color palettes for different entities
PLATFORM_COLORS = {
    'aws': '#FF9900',      # AWS Orange
    'azure': '#0089D6',    # Azure Blue
    'gcp': '#4285F4',      # Google Blue
    'local': '#808080'     # Gray
}

LANGUAGE_COLORS = {
    'python': '#3776AB',   # Python Blue
    'nodejs': '#339933',   # Node.js Green
    'rust': '#000000',     # Rust Black
    'java': '#007396',     # Java Blue
    'pypy': '#193440',     # PyPy Dark
    'cpp': '#00599C'       # C++ Blue
}


class BenchmarkVisualizer:
    """Creates visualizations from benchmark comparison results."""
    
    def __init__(self, results_file: str, output_dir: Optional[str] = None):
        self.results_file = Path(results_file)
        self.output_dir = Path(output_dir) if output_dir else self.results_file.parent / 'plots'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load results
        with open(self.results_file, 'r') as f:
            self.results = json.load(f)
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(levelname)s: %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        self.logger.info(f"Loaded results from {self.results_file}")
        self.logger.info(f"Plots will be saved to {self.output_dir}")
    
    def extract_dataframe(self) -> pd.DataFrame:
        """
        Extract benchmark results into a pandas DataFrame.
        
        Returns a DataFrame with columns:
        - benchmark: benchmark name
        - platform: cloud platform
        - language: programming language
        - version: language version
        - memory_mb: memory configuration
        - avg_time_ms: average execution time
        - min_time_ms: minimum execution time
        - max_time_ms: maximum execution time
        - cold_starts: number of cold starts
        - warm_starts: number of warm starts
        - success: whether the run succeeded
        """
        rows = []
        
        for benchmark, bench_data in self.results['benchmarks'].items():
            for platform, platform_data in bench_data.items():
                for language, lang_data in platform_data.items():
                    for version, version_data in lang_data.items():
                        for memory_config, result in version_data.items():
                            row = {
                                'benchmark': benchmark,
                                'platform': platform,
                                'language': language,
                                'version': version,
                                'memory_mb': result.get('memory_mb', 0),
                                'success': result.get('success', False)
                            }
                            
                            # Extract metrics if available
                            if 'metrics' in result:
                                metrics = result['metrics']
                                row['avg_time_ms'] = metrics.get('avg_execution_time_ms')
                                row['min_time_ms'] = metrics.get('min_execution_time_ms')
                                row['max_time_ms'] = metrics.get('max_execution_time_ms')
                                row['cold_starts'] = metrics.get('cold_starts', 0)
                                row['warm_starts'] = metrics.get('warm_starts', 0)
                                
                                # Store all execution times for detailed analysis
                                if 'execution_times_ms' in metrics:
                                    row['execution_times'] = metrics['execution_times_ms']
                            
                            rows.append(row)
        
        df = pd.DataFrame(rows)
        self.logger.info(f"Extracted {len(df)} benchmark results")
        return df
    
    def plot_language_comparison(self, df: pd.DataFrame, benchmark: Optional[str] = None):
        """
        Create bar chart comparing languages across platforms.
        
        Args:
            df: DataFrame with benchmark results
            benchmark: Optional benchmark name to filter by
        """
        if benchmark:
            df = df[df['benchmark'] == benchmark]
            title_suffix = f" - {benchmark}"
        else:
            title_suffix = " - All Benchmarks"
        
        # Filter successful runs only
        df = df[df['success'] == True].copy()
        
        if df.empty:
            self.logger.warning(f"No successful runs for language comparison{title_suffix}")
            return
        
        # Create grouped bar chart
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Group by platform and language
        grouped = df.groupby(['platform', 'language'])['avg_time_ms'].mean().reset_index()
        
        # Pivot for plotting
        pivot = grouped.pivot(index='language', columns='platform', values='avg_time_ms')
        
        # Create bar chart
        pivot.plot(kind='bar', ax=ax, color=[PLATFORM_COLORS.get(p, '#888888') for p in pivot.columns])
        
        ax.set_xlabel('Language')
        ax.set_ylabel('Average Execution Time (ms)')
        ax.set_title(f'Language Performance Comparison{title_suffix}')
        ax.legend(title='Platform')
        ax.grid(axis='y', alpha=0.3)
        
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        filename = f"language_comparison{'_' + benchmark if benchmark else ''}.png"
        filepath = self.output_dir / filename
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        self.logger.info(f"Saved: {filepath}")
        plt.close()
    
    def plot_platform_comparison(self, df: pd.DataFrame, language: Optional[str] = None):
        """
        Create bar chart comparing platforms for a specific language.
        
        Args:
            df: DataFrame with benchmark results
            language: Optional language to filter by
        """
        if language:
            df = df[df['language'] == language]
            title_suffix = f" - {language.title()}"
        else:
            title_suffix = ""
        
        # Filter successful runs only
        df = df[df['success'] == True].copy()
        
        if df.empty:
            self.logger.warning(f"No successful runs for platform comparison{title_suffix}")
            return
        
        # Create grouped bar chart
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Group by platform and benchmark
        grouped = df.groupby(['benchmark', 'platform'])['avg_time_ms'].mean().reset_index()
        
        # Pivot for plotting
        pivot = grouped.pivot(index='benchmark', columns='platform', values='avg_time_ms')
        
        # Create bar chart
        pivot.plot(kind='bar', ax=ax, color=[PLATFORM_COLORS.get(p, '#888888') for p in pivot.columns])
        
        ax.set_xlabel('Benchmark')
        ax.set_ylabel('Average Execution Time (ms)')
        ax.set_title(f'Platform Performance Comparison{title_suffix}')
        ax.legend(title='Platform')
        ax.grid(axis='y', alpha=0.3)
        
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        
        filename = f"platform_comparison{'_' + language if language else ''}.png"
        filepath = self.output_dir / filename
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        self.logger.info(f"Saved: {filepath}")
        plt.close()
    
    def plot_memory_scaling(self, df: pd.DataFrame, benchmark: Optional[str] = None):
        """
        Create line plot showing how performance scales with memory.
        
        Args:
            df: DataFrame with benchmark results
            benchmark: Optional benchmark to filter by
        """
        if benchmark:
            df = df[df['benchmark'] == benchmark]
            title_suffix = f" - {benchmark}"
        else:
            title_suffix = ""
        
        # Filter successful runs only
        df = df[df['success'] == True].copy()
        
        if df.empty or df['memory_mb'].nunique() < 2:
            self.logger.warning(f"Insufficient data for memory scaling plot{title_suffix}")
            return
        
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Plot for each language-platform combination
        for (language, platform), group in df.groupby(['language', 'platform']):
            group_sorted = group.sort_values('memory_mb')
            label = f"{language} ({platform})"
            color = LANGUAGE_COLORS.get(language, '#888888')
            linestyle = '-' if platform == 'aws' else '--' if platform == 'azure' else '-.'
            
            ax.plot(
                group_sorted['memory_mb'],
                group_sorted['avg_time_ms'],
                marker='o',
                label=label,
                color=color,
                linestyle=linestyle,
                linewidth=2
            )
        
        ax.set_xlabel('Memory (MB)')
        ax.set_ylabel('Average Execution Time (ms)')
        ax.set_title(f'Performance vs Memory{title_suffix}')
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        ax.grid(alpha=0.3)
        
        plt.tight_layout()
        
        filename = f"memory_scaling{'_' + benchmark if benchmark else ''}.png"
        filepath = self.output_dir / filename
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        self.logger.info(f"Saved: {filepath}")
        plt.close()
    
    def plot_cold_vs_warm(self, df: pd.DataFrame):
        """
        Create stacked bar chart showing cold vs warm start distribution.
        
        Args:
            df: DataFrame with benchmark results
        """
        # Filter successful runs only
        df = df[df['success'] == True].copy()
        
        if df.empty or 'cold_starts' not in df.columns:
            self.logger.warning("No cold start data available")
            return
        
        # Calculate totals
        df['total_invocations'] = df['cold_starts'] + df['warm_starts']
        
        # Filter out rows with no invocations
        df = df[df['total_invocations'] > 0]
        
        if df.empty:
            self.logger.warning("No invocation data for cold vs warm plot")
            return
        
        fig, ax = plt.subplots(figsize=(14, 6))
        
        # Group by language and platform
        grouped = df.groupby(['language', 'platform']).agg({
            'cold_starts': 'sum',
            'warm_starts': 'sum'
        }).reset_index()
        
        # Create labels
        grouped['label'] = grouped['language'] + '\n(' + grouped['platform'] + ')'
        
        # Create stacked bar chart
        x = np.arange(len(grouped))
        width = 0.6
        
        p1 = ax.bar(x, grouped['cold_starts'], width, label='Cold Starts', color='#d62728')
        p2 = ax.bar(x, grouped['warm_starts'], width, bottom=grouped['cold_starts'],
                    label='Warm Starts', color='#2ca02c')
        
        ax.set_xlabel('Language (Platform)')
        ax.set_ylabel('Number of Invocations')
        ax.set_title('Cold vs Warm Start Distribution')
        ax.set_xticks(x)
        ax.set_xticklabels(grouped['label'], rotation=45, ha='right')
        ax.legend()
        ax.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        
        filepath = self.output_dir / "cold_vs_warm_starts.png"
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        self.logger.info(f"Saved: {filepath}")
        plt.close()
    
    def plot_heatmap(self, df: pd.DataFrame, metric: str = 'avg_time_ms'):
        """
        Create heatmap showing performance across platforms and languages.
        
        Args:
            df: DataFrame with benchmark results
            metric: Metric to visualize
        """
        # Filter successful runs only
        df = df[df['success'] == True].copy()
        
        if df.empty or metric not in df.columns:
            self.logger.warning(f"No data available for heatmap with metric: {metric}")
            return
        
        # Aggregate by platform and language
        pivot = df.groupby(['platform', 'language'])[metric].mean().reset_index()
        pivot_table = pivot.pivot(index='platform', columns='language', values=metric)
        
        if pivot_table.empty:
            self.logger.warning("No data for heatmap")
            return
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        sns.heatmap(
            pivot_table,
            annot=True,
            fmt='.2f',
            cmap='YlOrRd',
            ax=ax,
            cbar_kws={'label': 'Avg Execution Time (ms)'}
        )
        
        ax.set_title(f'Performance Heatmap - {metric.replace("_", " ").title()}')
        ax.set_xlabel('Language')
        ax.set_ylabel('Platform')
        
        plt.tight_layout()
        
        filepath = self.output_dir / f"heatmap_{metric}.png"
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        self.logger.info(f"Saved: {filepath}")
        plt.close()
    
    def plot_version_comparison(self, df: pd.DataFrame, language: str):
        """
        Compare different versions of the same language.
        
        Args:
            df: DataFrame with benchmark results
            language: Language to compare versions for
        """
        df = df[df['language'] == language]
        df = df[df['success'] == True].copy()
        
        if df.empty or df['version'].nunique() < 2:
            self.logger.warning(f"Insufficient version data for {language}")
            return
        
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Group by version and platform
        grouped = df.groupby(['version', 'platform'])['avg_time_ms'].mean().reset_index()
        pivot = grouped.pivot(index='version', columns='platform', values='avg_time_ms')
        
        pivot.plot(kind='bar', ax=ax, color=[PLATFORM_COLORS.get(p, '#888888') for p in pivot.columns])
        
        ax.set_xlabel(f'{language.title()} Version')
        ax.set_ylabel('Average Execution Time (ms)')
        ax.set_title(f'{language.title()} Version Performance Comparison')
        ax.legend(title='Platform')
        ax.grid(axis='y', alpha=0.3)
        
        plt.xticks(rotation=0)
        plt.tight_layout()
        
        filepath = self.output_dir / f"version_comparison_{language}.png"
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        self.logger.info(f"Saved: {filepath}")
        plt.close()
    
    def create_summary_report(self, df: pd.DataFrame):
        """
        Create a text summary report of the benchmark results.
        
        Args:
            df: DataFrame with benchmark results
        """
        report_lines = []
        report_lines.append("="*80)
        report_lines.append("BENCHMARK COMPARISON SUMMARY REPORT")
        report_lines.append("="*80)
        report_lines.append("")
        
        # Metadata
        metadata = self.results.get('metadata', {})
        report_lines.append(f"Start Time: {metadata.get('start_time', 'N/A')}")
        report_lines.append(f"End Time: {metadata.get('end_time', 'N/A')}")
        report_lines.append("")
        
        # Summary statistics
        if 'summary' in metadata:
            summary = metadata['summary']
            report_lines.append("Overall Statistics:")
            report_lines.append(f"  Total Runs: {summary.get('total_runs', 0)}")
            report_lines.append(f"  Successful: {summary.get('successful', 0)}")
            report_lines.append(f"  Failed: {summary.get('failed', 0)}")
            report_lines.append(f"  Success Rate: {summary.get('success_rate', 'N/A')}")
            report_lines.append("")
        
        # Successful runs only
        df_success = df[df['success'] == True].copy()
        
        if not df_success.empty and 'avg_time_ms' in df_success.columns:
            report_lines.append("Performance by Platform:")
            for platform in sorted(df_success['platform'].unique()):
                platform_df = df_success[df_success['platform'] == platform]
                avg_time = platform_df['avg_time_ms'].mean()
                report_lines.append(f"  {platform.upper()}: {avg_time:.2f} ms (avg)")
            report_lines.append("")
            
            report_lines.append("Performance by Language:")
            for language in sorted(df_success['language'].unique()):
                lang_df = df_success[df_success['language'] == language]
                avg_time = lang_df['avg_time_ms'].mean()
                report_lines.append(f"  {language}: {avg_time:.2f} ms (avg)")
            report_lines.append("")
            
            # Best performers
            report_lines.append("Best Performers:")
            # Check if we have valid data
            if not df_success['avg_time_ms'].isna().all():
                best_overall = df_success.loc[df_success['avg_time_ms'].idxmin()]
                report_lines.append(
                    f"  Fastest Overall: {best_overall['language']} on {best_overall['platform']} "
                    f"({best_overall['avg_time_ms']:.2f} ms)"
                )
            else:
                report_lines.append("  No valid performance data available")
            
            for platform in df_success['platform'].unique():
                platform_df = df_success[df_success['platform'] == platform]
                if not platform_df.empty and not platform_df['avg_time_ms'].isna().all():
                    best = platform_df.loc[platform_df['avg_time_ms'].idxmin()]
                    report_lines.append(
                        f"  Fastest on {platform}: {best['language']} v{best['version']} "
                        f"({best['avg_time_ms']:.2f} ms)"
                    )
            report_lines.append("")
        
        report_lines.append("="*80)
        
        # Write report
        report_text = "\n".join(report_lines)
        filepath = self.output_dir / "summary_report.txt"
        with open(filepath, 'w') as f:
            f.write(report_text)
        
        self.logger.info(f"Saved: {filepath}")
        print("\n" + report_text)
    
    def create_all_plots(self):
        """Generate all available plots from the benchmark results."""
        self.logger.info("Generating all plots...")
        
        df = self.extract_dataframe()
        
        if df.empty:
            self.logger.error("No data to plot!")
            return
        
        # Create summary report
        self.create_summary_report(df)
        
        # Language comparison
        self.plot_language_comparison(df)
        
        # Platform comparison
        self.plot_platform_comparison(df)
        
        # Memory scaling
        if df['memory_mb'].nunique() > 1:
            self.plot_memory_scaling(df)
        
        # Cold vs warm starts
        if 'cold_starts' in df.columns:
            self.plot_cold_vs_warm(df)
        
        # Heatmap
        self.plot_heatmap(df)
        
        # Version comparisons for each language
        for language in df['language'].unique():
            if df[df['language'] == language]['version'].nunique() > 1:
                self.plot_version_comparison(df, language)
        
        # Per-benchmark plots
        for benchmark in df['benchmark'].unique():
            self.plot_language_comparison(df, benchmark=benchmark)
            
        self.logger.info(f"\n✓ All plots generated in: {self.output_dir}")


def main():
    parser = argparse.ArgumentParser(
        description='Visualize cross-platform benchmark comparison results',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate all plots
  %(prog)s results/comparison_20241212/comparison_results.json

  # Specify output directory
  %(prog)s results/comparison_20241212/comparison_results.json --output plots/

  # Generate specific plot types
  %(prog)s results.json --plot-type language_comparison platform_comparison
        """
    )
    
    parser.add_argument('results_file',
                        help='Path to comparison_results.json file')
    parser.add_argument('--output', '-o',
                        help='Output directory for plots (default: results_dir/plots)')
    parser.add_argument('--plot-type', nargs='+',
                        choices=['language_comparison', 'platform_comparison', 
                                'memory_scaling', 'cold_warm', 'heatmap', 'versions', 'all'],
                        default=['all'],
                        help='Types of plots to generate (default: all)')
    parser.add_argument('--language', '-l',
                        help='Filter by specific language')
    parser.add_argument('--benchmark', '-b',
                        help='Filter by specific benchmark')
    parser.add_argument('--format', choices=['png', 'pdf', 'svg'], default='png',
                        help='Output format for plots (default: png)')
    
    args = parser.parse_args()
    
    try:
        visualizer = BenchmarkVisualizer(args.results_file, args.output)
        
        if 'all' in args.plot_type:
            visualizer.create_all_plots()
        else:
            df = visualizer.extract_dataframe()
            
            if 'language_comparison' in args.plot_type:
                visualizer.plot_language_comparison(df, benchmark=args.benchmark)
            
            if 'platform_comparison' in args.plot_type:
                visualizer.plot_platform_comparison(df, language=args.language)
            
            if 'memory_scaling' in args.plot_type:
                visualizer.plot_memory_scaling(df, benchmark=args.benchmark)
            
            if 'cold_warm' in args.plot_type:
                visualizer.plot_cold_vs_warm(df)
            
            if 'heatmap' in args.plot_type:
                visualizer.plot_heatmap(df)
            
            if 'versions' in args.plot_type and args.language:
                visualizer.plot_version_comparison(df, args.language)
            
            visualizer.create_summary_report(df)
        
        print(f"\n✓ Visualization complete! Plots saved to: {visualizer.output_dir}")
        return 0
        
    except FileNotFoundError:
        print(f"Error: Results file not found: {args.results_file}")
        return 1
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in results file: {args.results_file}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

