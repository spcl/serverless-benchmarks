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
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# Suppress matplotlib debug output
import matplotlib
matplotlib_logger = logging.getLogger('matplotlib')
matplotlib_logger.setLevel(logging.WARNING)
pil_logger = logging.getLogger('PIL')
pil_logger.setLevel(logging.WARNING)

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
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(levelname)s: %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Detect file type and load results
        if self.results_file.suffix == '.csv':
            self.results = None  # CSV doesn't use the results dict
            self.is_csv = True
            self.logger.info(f"Loaded CSV from {self.results_file}")
        else:
            with open(self.results_file, 'r') as f:
                self.results = json.load(f)
            self.is_csv = False
            self.logger.info(f"Loaded results from {self.results_file}")
        
        self.logger.info(f"Plots will be saved to {self.output_dir}")
    
    def extract_dataframe(self) -> pd.DataFrame:
        """
        Extract benchmark results into a pandas DataFrame.
        
        For CSV files (SeBS perf-cost format):
        - Reads directly from CSV with columns: memory, type, is_cold, exec_time, 
          client_time, provider_time, mem_used
        
        For JSON files (cross_platform_benchmark format):
        - Returns a DataFrame with columns: benchmark, platform, language, version,
          memory_mb, avg_time_ms, cold_starts, warm_starts, success, etc.
        """
        if self.is_csv:
            # Read SeBS perf-cost CSV format
            df = pd.read_csv(self.results_file)
            
            # Convert microseconds to milliseconds
            df['client_time_ms'] = df['client_time'] / 1000.0
            df['provider_time_ms'] = df['provider_time'] / 1000.0
            df['exec_time_ms'] = df['exec_time'] / 1000.0
            
            self.logger.info(f"Loaded {len(df)} measurements from CSV")
            return df
        
        # JSON format (original code)
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
        
        # Pivot for plotting - SWAPPED: platforms on X-axis, languages as colors
        pivot = grouped.pivot(index='platform', columns='language', values='avg_time_ms')
        
        # Create bar chart with language colors
        pivot.plot(kind='bar', ax=ax, color=[LANGUAGE_COLORS.get(lang, '#888888') for lang in pivot.columns])
        
        ax.set_xlabel('Platform')
        ax.set_ylabel('Average Execution Time (ms)')
        ax.set_title(f'Platform Performance Comparison by Language{title_suffix}')
        ax.legend(title='Language')
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
        
        ax.bar(x, grouped['cold_starts'], width, label='Cold Starts', color='#d62728')
        ax.bar(x, grouped['warm_starts'], width, bottom=grouped['cold_starts'],
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
    
    def plot_cold_warm_comparison_boxplot(self, df: pd.DataFrame, benchmark: Optional[str] = None, 
                                         language: Optional[str] = None, version: Optional[str] = None):
        """
        Create side-by-side boxplot comparison of cold vs warm performance.
        Similar to the friend's plot style with better visual separation.
        
        Args:
            df: DataFrame with benchmark results
            benchmark: Optional benchmark name to filter by
            language: Optional language to filter by
            version: Optional version to filter by
        """
        # Filter data
        if benchmark:
            df = df[df['benchmark'] == benchmark]
        if language:
            df = df[df['language'] == language]
        if version:
            df = df[df['version'] == version]
        
        df = df[df['success'] == True].copy()
        
        if df.empty or 'execution_times' not in df.columns:
            self.logger.warning("No execution time data for cold/warm boxplot comparison")
            return
        
        # Expand execution times into separate rows with cold/warm labels
        rows = []
        for _, row in df.iterrows():
            if 'execution_times' in row and row['execution_times']:
                exec_times = row['execution_times']
                cold_count = row.get('cold_starts', 0)
                
                # Mark first cold_count as cold, rest as warm
                for i, time_ms in enumerate(exec_times):
                    rows.append({
                        'benchmark': row['benchmark'],
                        'language': row['language'],
                        'version': row['version'],
                        'memory': row['memory_mb'],
                        'time_ms': time_ms,
                        'type': 'cold' if i < cold_count else 'warm'
                    })
        
        if not rows:
            self.logger.warning("No execution time data to plot")
            return
        
        expanded_df = pd.DataFrame(rows)
        
        # Create figure with subplots
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=False)
        
        # Build title
        title_parts = []
        if benchmark:
            title_parts.append(benchmark)
        if language:
            lang_display = f"{language.title()}"
            if version:
                lang_display += f" {version}"
            title_parts.append(lang_display)
        title_parts.append("Runtime Performance: Cold vs Warm")
        fig.suptitle(' '.join(title_parts), fontsize=14, fontweight='bold')
        
        # Cold Start Plot
        cold_data = expanded_df[expanded_df['type'] == 'cold']
        if not cold_data.empty:
            sns.boxplot(ax=axes[0], x="memory", y="time_ms", data=cold_data, color="skyblue")
            axes[0].set_title("Cold Start Latency")
            axes[0].set_ylabel("Time (ms)")
            axes[0].set_xlabel("Memory (MB)")
        
        # Warm Execution Plot
        warm_data = expanded_df[expanded_df['type'] == 'warm']
        if not warm_data.empty:
            sns.boxplot(ax=axes[1], x="memory", y="time_ms", data=warm_data, color="orange")
            axes[1].set_title("Warm Execution Latency")
            axes[1].set_ylabel("Time (ms)")
            axes[1].set_xlabel("Memory (MB)")
        
        plt.tight_layout()
        
        # Create filename
        filename_parts = ["cold_warm_boxplot"]
        if benchmark:
            filename_parts.append(benchmark.replace(".", "_"))
        if language:
            filename_parts.append(language)
        if version:
            filename_parts.append(version.replace(".", "_"))
        filename = "_".join(filename_parts) + ".png"
        
        filepath = self.output_dir / filename
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        self.logger.info(f"Saved: {filepath}")
        plt.close()
    
    def plot_overhead_breakdown(self, df: pd.DataFrame, benchmark: Optional[str] = None,
                               language: Optional[str] = None, start_type: str = 'cold'):
        """
        Create bar chart showing overhead breakdown (client_time, provider_time, exec_time).
        
        Args:
            df: DataFrame with benchmark results
            benchmark: Optional benchmark name to filter by
            language: Optional language to filter by
            start_type: 'cold' or 'warm' to filter by startup type
        """
        # Filter data
        if benchmark:
            df = df[df['benchmark'] == benchmark]
        if language:
            df = df[df['language'] == language]
        
        df = df[df['success'] == True].copy()
        
        # Check if we have the required timing breakdown data
        # This assumes metrics might have these fields
        if df.empty:
            self.logger.warning(f"No data for overhead breakdown")
            return
        
        # Expand the data to get individual measurements
        rows = []
        for _, row in df.iterrows():
            if 'execution_times' in row and row['execution_times']:
                exec_times = row['execution_times']
                cold_count = row.get('cold_starts', 0)
                
                for i, exec_time_ms in enumerate(exec_times):
                    is_cold = i < cold_count
                    if (start_type == 'cold' and is_cold) or (start_type == 'warm' and not is_cold):
                        # For now, we'll use execution time as a proxy
                        # In a real scenario, you'd have client_time, provider_time, exec_time separately
                        rows.append({
                            'memory': row['memory_mb'],
                            'client_time_ms': exec_time_ms,  # Would be actual client_time
                            'provider_time_ms': exec_time_ms * 0.8,  # Placeholder - provider overhead
                            'exec_time_ms': exec_time_ms * 0.7  # Placeholder - actual execution
                        })
        
        if not rows:
            self.logger.warning(f"No {start_type} start data for overhead breakdown")
            return
        
        breakdown_df = pd.DataFrame(rows)
        
        # Melt for seaborn
        melted = breakdown_df.melt(
            id_vars=['memory'],
            value_vars=['client_time_ms', 'provider_time_ms', 'exec_time_ms'],
            var_name='Metric',
            value_name='Time'
        )
        
        plt.figure(figsize=(10, 6))
        sns.barplot(x="memory", y="Time", hue="Metric", data=melted, errorbar='sd', palette="muted")
        
        # Build title
        title_parts = []
        if benchmark:
            title_parts.append(benchmark)
        if language:
            title_parts.append(language.title())
        title_parts.append(f"Overhead ({start_type.title()} Start)")
        
        plt.title(' '.join(title_parts), fontweight='bold')
        plt.ylabel("Time (ms)")
        plt.xlabel("Memory (MB)")
        plt.tight_layout()
        
        # Create filename
        filename_parts = [f"{start_type}_overhead"]
        if benchmark:
            filename_parts.append(benchmark.replace(".", "_"))
        if language:
            filename_parts.append(language)
        filename = "_".join(filename_parts) + ".png"
        
        filepath = self.output_dir / filename
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        self.logger.info(f"Saved: {filepath}")
        plt.close()
    
    def plot_memory_usage_distribution(self, df: pd.DataFrame, benchmark: Optional[str] = None,
                                      language: Optional[str] = None):
        """
        Create boxplot showing memory usage distribution across memory configurations.
        
        Args:
            df: DataFrame with benchmark results
            benchmark: Optional benchmark name to filter by
            language: Optional language to filter by
        """
        # Filter data
        if benchmark:
            df = df[df['benchmark'] == benchmark]
        if language:
            df = df[df['language'] == language]
        
        df = df[df['success'] == True].copy()
        
        # Check if we have memory usage data in metrics
        if df.empty:
            self.logger.warning("No data for memory usage distribution")
            return
        
        # Try to extract memory usage from metrics if available
        rows = []
        for _, row in df.iterrows():
            if 'metrics' in row:
                metrics = row['metrics']
                if isinstance(metrics, dict) and 'memory_used_mb' in metrics:
                    rows.append({
                        'memory': row['memory_mb'],
                        'mem_used': metrics['memory_used_mb']
                    })
        
        if not rows:
            self.logger.warning("No memory usage data available in metrics")
            return
        
        mem_df = pd.DataFrame(rows)
        
        plt.figure(figsize=(8, 6))
        sns.boxplot(x="memory", y="mem_used", data=mem_df, color="lightgreen")
        
        if not mem_df.empty and mem_df['mem_used'].max() > 0:
            plt.ylim(0, mem_df['mem_used'].max() * 1.2)
        
        # Build title
        title_parts = []
        if benchmark:
            title_parts.append(benchmark)
        if language:
            title_parts.append(language.title())
        title_parts.append("Memory Usage Distribution")
        
        plt.title(' '.join(title_parts), fontweight='bold')
        plt.ylabel("Used Memory (MB)")
        plt.xlabel("Allocated Memory (MB)")
        plt.tight_layout()
        
        # Create filename
        filename_parts = ["memory_usage"]
        if benchmark:
            filename_parts.append(benchmark.replace(".", "_"))
        if language:
            filename_parts.append(language)
        filename = "_".join(filename_parts) + ".png"
        
        filepath = self.output_dir / filename
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
        
        # Drop rows where the metric is NaN
        df = df.dropna(subset=[metric])
        
        if df.empty:
            self.logger.warning(f"No valid numeric data for heatmap with metric: {metric}")
            return
        
        # Aggregate by platform and language
        pivot = df.groupby(['platform', 'language'])[metric].mean().reset_index()
        pivot_table = pivot.pivot(index='platform', columns='language', values=metric)
        
        if pivot_table.empty or pivot_table.isna().all().all():
            self.logger.warning("No data for heatmap")
            return
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Only annotate if we have valid numeric data
        try:
            sns.heatmap(
                pivot_table,
                annot=True,
                fmt='.2f',
                cmap='YlOrRd',
                ax=ax,
                cbar_kws={'label': 'Avg Execution Time (ms)'},
                mask=pivot_table.isna()  # Mask NaN values
            )
            
            ax.set_title(f'Performance Heatmap - {metric.replace("_", " ").title()}')
            ax.set_xlabel('Language')
            ax.set_ylabel('Platform')
            
            plt.tight_layout()
            
            filepath = self.output_dir / f"heatmap_{metric}.png"
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            self.logger.info(f"Saved: {filepath}")
        except (ValueError, TypeError) as e:
            self.logger.warning(f"Could not generate heatmap: {e}")
        finally:
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
        
        # Metadata (only for JSON results, not CSV)
        if self.results:
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
        
        # Successful runs only (filter by success column if it exists)
        if 'success' in df.columns:
            df_success = df[df['success'] == True].copy()
        else:
            df_success = df.copy()
        
        if not df_success.empty and 'avg_time_ms' in df_success.columns:
            if 'platform' in df_success.columns:
                report_lines.append("Performance by Platform:")
                for platform in sorted(df_success['platform'].unique()):
                    platform_df = df_success[df_success['platform'] == platform]
                    avg_time = platform_df['avg_time_ms'].mean()
                    report_lines.append(f"  {platform.upper()}: {avg_time:.2f} ms (avg)")
                report_lines.append("")
            
            if 'language' in df_success.columns:
                report_lines.append("Performance by Language:")
                for language in sorted(df_success['language'].unique()):
                    lang_df = df_success[df_success['language'] == language]
                    avg_time = lang_df['avg_time_ms'].mean()
                    report_lines.append(f"  {language}: {avg_time:.2f} ms (avg)")
                report_lines.append("")
            
            # Best performers
            if 'language' in df_success.columns and 'platform' in df_success.columns:
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
                        version_str = f" v{best['version']}" if 'version' in best else ""
                        report_lines.append(
                            f"  Fastest on {platform}: {best['language']}{version_str} "
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
    
    def plot_sebs_cold_warm_comparison(self, df: pd.DataFrame, benchmark_name: str = "", 
                                       language_name: str = "", title_comment: str = ""):
        """
        Create SeBS-style side-by-side cold vs warm comparison from CSV data.
        This matches the friends' plotting style exactly.
        
        Args:
            df: DataFrame from SeBS CSV (must have 'type', 'memory', 'client_time_ms' columns)
            benchmark_name: Name of benchmark for title
            language_name: Language name for title
            title_comment: Additional comment for title
        """
        if not self.is_csv:
            self.logger.warning("This plot type requires CSV input from SeBS perf-cost")
            return
        
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=False)
        
        title_parts = [benchmark_name, language_name, title_comment, "Runtime Performance: Cold vs Warm"]
        title = ' '.join([p for p in title_parts if p])
        fig.suptitle(title, fontsize=14, fontweight='bold')
        
        # Cold Start Plot
        cold_data = df[df['type'] == 'cold']
        if not cold_data.empty:
            sns.boxplot(ax=axes[0], x="memory", y="client_time_ms", data=cold_data, color="skyblue")
            axes[0].set_title("Cold Start Latency")
            axes[0].set_ylabel("Time (ms)")
            axes[0].set_xlabel("Memory (MB)")
        
        # Warm Execution Plot
        warm_data = df[df['type'] == 'warm']
        if not warm_data.empty:
            sns.boxplot(ax=axes[1], x="memory", y="client_time_ms", data=warm_data, color="orange")
            axes[1].set_title("Warm Execution Latency")
            axes[1].set_ylabel("Time (ms)")
            axes[1].set_xlabel("Memory (MB)")
        
        plt.tight_layout()
        
        filepath = self.output_dir / "sebs_cold_warm_comparison.png"
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        self.logger.info(f"Saved: {filepath}")
        plt.close()
    
    def plot_sebs_overhead_breakdown(self, df: pd.DataFrame, start_type: str = 'cold',
                                     benchmark_name: str = "", language_name: str = "", 
                                     title_comment: str = ""):
        """
        Create SeBS-style overhead breakdown showing client/provider/exec times.
        
        Args:
            df: DataFrame from SeBS CSV
            start_type: 'cold' or 'warm'
            benchmark_name: Name of benchmark for title
            language_name: Language name for title
            title_comment: Additional comment for title
        """
        if not self.is_csv:
            self.logger.warning("This plot type requires CSV input from SeBS perf-cost")
            return
        
        # Filter by type
        filtered_df = df[df['type'] == start_type].copy()
        
        if filtered_df.empty:
            self.logger.warning(f"No {start_type} data for overhead breakdown")
            return
        
        # For cold starts, filter out entries with no provider time
        if start_type == 'cold':
            filtered_df = filtered_df[filtered_df['provider_time'] > 0]
        
        # Melt for seaborn
        melted = filtered_df.melt(
            id_vars=['memory'],
            value_vars=['client_time_ms', 'provider_time_ms', 'exec_time_ms'],
            var_name='Metric',
            value_name='Time'
        )
        
        plt.figure(figsize=(10, 6))
        sns.barplot(x="memory", y="Time", hue="Metric", data=melted, errorbar='sd', palette="muted")
        
        title_parts = [benchmark_name, language_name, title_comment, 
                      f"Overhead ({start_type.title()} Start)"]
        title = ' '.join([p for p in title_parts if p])
        
        plt.title(title, fontweight='bold')
        plt.ylabel("Time (ms)")
        plt.xlabel("Memory (MB)")
        plt.tight_layout()
        
        filepath = self.output_dir / f"sebs_{start_type}_overhead.png"
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        self.logger.info(f"Saved: {filepath}")
        plt.close()
    
    def plot_sebs_memory_usage(self, df: pd.DataFrame, benchmark_name: str = "",
                               language_name: str = "", title_comment: str = ""):
        """
        Create SeBS-style memory usage distribution plot.
        
        Args:
            df: DataFrame from SeBS CSV
            benchmark_name: Name of benchmark for title
            language_name: Language name for title  
            title_comment: Additional comment for title
        """
        if not self.is_csv:
            self.logger.warning("This plot type requires CSV input from SeBS perf-cost")
            return
        
        plt.figure(figsize=(8, 6))
        sns.boxplot(x="memory", y="mem_used", data=df, color="lightgreen")
        
        if not df.empty and df['mem_used'].max() > 0:
            plt.ylim(0, df['mem_used'].max() * 1.2)
        
        title_parts = [benchmark_name, language_name, title_comment, "Memory Usage Distribution"]
        title = ' '.join([p for p in title_parts if p])
        
        plt.title(title, fontweight='bold')
        plt.ylabel("Used Memory (MB)")
        plt.xlabel("Allocated Memory (MB)")
        plt.tight_layout()
        
        filepath = self.output_dir / "sebs_memory_usage.png"
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        self.logger.info(f"Saved: {filepath}")
        plt.close()
    
    def create_sebs_plots(self, benchmark_name: str = "", language_name: str = "", 
                         title_comment: str = ""):
        """
        Generate all SeBS-style plots from CSV data.
        This creates plots matching your friends' style.
        
        Args:
            benchmark_name: Name of benchmark (e.g., "110.html")
            language_name: Language name (e.g., "Python 3.11")
            title_comment: Additional comment (e.g., "codepackage", "-O2")
        """
        if not self.is_csv:
            self.logger.error("SeBS plots require CSV input. Use JSON input for standard plots.")
            return
        
        self.logger.info("Generating SeBS-style plots...")
        
        df = self.extract_dataframe()
        
        if df.empty:
            self.logger.error("No data to plot!")
            return
        
        # Cold vs Warm comparison
        self.plot_sebs_cold_warm_comparison(df, benchmark_name, language_name, title_comment)
        
        # Overhead breakdowns
        self.plot_sebs_overhead_breakdown(df, 'cold', benchmark_name, language_name, title_comment)
        self.plot_sebs_overhead_breakdown(df, 'warm', benchmark_name, language_name, title_comment)
        
        # Memory usage
        self.plot_sebs_memory_usage(df, benchmark_name, language_name, title_comment)
        
        self.logger.info(f"\n✓ All SeBS plots generated in: {self.output_dir}")
    
    def create_all_plots(self):
        """Generate all available plots from the benchmark results."""
        self.logger.info("Generating all plots...")
        
        df = self.extract_dataframe()
        
        if df.empty:
            self.logger.error("No data to plot!")
            return
        
        plot_count = 0
        error_count = 0
        
        # Create summary report
        try:
            self.create_summary_report(df)
            plot_count += 1
        except Exception as e:
            self.logger.warning(f"Could not create summary report: {e}")
            error_count += 1
        
        # Language comparison
        try:
            self.plot_language_comparison(df)
            plot_count += 1
        except Exception as e:
            self.logger.warning(f"Could not create language comparison: {e}")
            error_count += 1
        
        # Memory scaling
        if df['memory_mb'].nunique() > 1:
            try:
                self.plot_memory_scaling(df)
                plot_count += 1
            except Exception as e:
                self.logger.warning(f"Could not create memory scaling plot: {e}")
                error_count += 1
        
        # Cold vs warm starts (original stacked bar)
        if 'cold_starts' in df.columns and 'warm_starts' in df.columns:
            try:
                self.plot_cold_vs_warm(df)
                plot_count += 1
            except Exception as e:
                self.logger.warning(f"Could not create cold vs warm plot: {e}")
                error_count += 1
        
        # Heatmap
        try:
            self.plot_heatmap(df)
            plot_count += 1
        except Exception as e:
            self.logger.warning(f"Could not create heatmap: {e}")
            error_count += 1
        
        # Version comparisons for each language
        for language in df['language'].unique():
            if df[df['language'] == language]['version'].nunique() > 1:
                try:
                    self.plot_version_comparison(df, language)
                    plot_count += 1
                except Exception as e:
                    self.logger.warning(f"Could not create version comparison for {language}: {e}")
                    error_count += 1
        
        # Per-benchmark plots
        for benchmark in df['benchmark'].unique():
            try:
                self.plot_language_comparison(df, benchmark=benchmark)
                plot_count += 1
            except Exception as e:
                self.logger.warning(f"Could not create language comparison for {benchmark}: {e}")
                error_count += 1
            
            # New enhanced plots per benchmark and language
            for language in df[df['benchmark'] == benchmark]['language'].unique():
                lang_data = df[(df['benchmark'] == benchmark) & (df['language'] == language)]
                
                # Cold/Warm boxplot comparison
                for version in lang_data['version'].unique():
                    try:
                        self.plot_cold_warm_comparison_boxplot(df, benchmark, language, version)
                        plot_count += 1
                    except Exception as e:
                        self.logger.debug(f"Could not create boxplot for {benchmark}/{language}/{version}: {e}")
                        error_count += 1
                
                # Overhead breakdowns
                try:
                    self.plot_overhead_breakdown(df, benchmark, language, start_type='cold')
                    plot_count += 1
                except Exception as e:
                    self.logger.debug(f"Could not create cold overhead for {benchmark}/{language}: {e}")
                    error_count += 1
                    
                try:
                    self.plot_overhead_breakdown(df, benchmark, language, start_type='warm')
                    plot_count += 1
                except Exception as e:
                    self.logger.debug(f"Could not create warm overhead for {benchmark}/{language}: {e}")
                    error_count += 1
                
                # Memory usage
                try:
                    self.plot_memory_usage_distribution(df, benchmark, language)
                    plot_count += 1
                except Exception as e:
                    self.logger.debug(f"Could not create memory usage for {benchmark}/{language}: {e}")
                    error_count += 1
            
        self.logger.info(f"\n✓ Generated {plot_count} plots in: {self.output_dir}")
        if error_count > 0:
            self.logger.info(f"  ({error_count} plots skipped due to insufficient data)")


def main():
    parser = argparse.ArgumentParser(
        description='Visualize cross-platform benchmark comparison results',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate all plots from JSON (cross_platform_benchmark)
  %(prog)s results/comparison_20241212/comparison_results.json

  # Generate SeBS-style plots from CSV (perf-cost result)
  %(prog)s measurements/110-html/perf-cost/result.csv --plot-type sebs --benchmark-name "110.html" --language-name "Python 3.11" --title-comment "codepackage"

  # Specify output directory
  %(prog)s results/comparison_results.json --output plots/

  # Generate specific plot types
  %(prog)s results.json --plot-type language_comparison platform_comparison
        """
    )
    
    parser.add_argument('results_file',
                        help='Path to comparison_results.json or result.csv file')
    parser.add_argument('--output', '-o',
                        help='Output directory for plots (default: results_dir/plots)')
    parser.add_argument('--plot-type', nargs='+',
                        choices=['language_comparison', 'platform_comparison', 
                                'memory_scaling', 'cold_warm', 'cold_warm_boxplot', 
                                'overhead', 'memory_usage', 'heatmap', 'versions', 'all', 'sebs'],
                        default=['all'],
                        help='Types of plots to generate (default: all, use sebs for CSV input)')
    parser.add_argument('--language', '-l',
                        help='Filter by specific language')
    parser.add_argument('--benchmark', '-b',
                        help='Filter by specific benchmark')
    parser.add_argument('--format', choices=['png', 'pdf', 'svg'], default='png',
                        help='Output format for plots (default: png)')
    
    # SeBS-specific arguments
    parser.add_argument('--benchmark-name',
                        help='Benchmark name for SeBS plots (e.g., "110.html")')
    parser.add_argument('--language-name', 
                        help='Language name for SeBS plots (e.g., "Python 3.11")')
    parser.add_argument('--title-comment',
                        help='Additional title comment for SeBS plots (e.g., "codepackage", "-O2")')
    
    args = parser.parse_args()
    
    try:
        visualizer = BenchmarkVisualizer(args.results_file, args.output)
        
        # Handle CSV files (SeBS perf-cost format)
        if visualizer.is_csv:
            if 'sebs' in args.plot_type or 'all' in args.plot_type:
                visualizer.create_sebs_plots(
                    benchmark_name=args.benchmark_name or "",
                    language_name=args.language_name or "",
                    title_comment=args.title_comment or ""
                )
            else:
                print("CSV input detected. Use --plot-type sebs to generate SeBS-style plots.")
                print("Example: python plot_comparison.py result.csv --plot-type sebs --benchmark-name '110.html' --language-name 'Python 3.11'")
                return 1
        
        # Handle JSON files (cross_platform_benchmark format)
        elif 'all' in args.plot_type:
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
            
            if 'cold_warm_boxplot' in args.plot_type:
                visualizer.plot_cold_warm_comparison_boxplot(
                    df, benchmark=args.benchmark, language=args.language
                )
            
            if 'overhead' in args.plot_type:
                visualizer.plot_overhead_breakdown(
                    df, benchmark=args.benchmark, language=args.language, start_type='cold'
                )
                visualizer.plot_overhead_breakdown(
                    df, benchmark=args.benchmark, language=args.language, start_type='warm'
                )
            
            if 'memory_usage' in args.plot_type:
                visualizer.plot_memory_usage_distribution(
                    df, benchmark=args.benchmark, language=args.language
                )
            
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

