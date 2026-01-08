#!/bin/bash

# Convenience wrapper for running benchmark comparisons and generating plots

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
BENCHMARKS="010.sleep"
PLATFORMS="aws"
LANGUAGES="python"
CONFIG="${PROJECT_ROOT}/config/example.json"
OUTPUT_DIR="${PROJECT_ROOT}/results/comparison_$(date +%Y%m%d_%H%M%S)"
REPETITIONS=5
MEMORY="256"
INPUT_SIZE="test"
ARCHITECTURE="x64"
GENERATE_PLOTS=true
CONTAINER_DEPLOYMENT=false
CONTAINER_DEPLOYMENT_FOR=""

# Print usage
usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Run cross-platform benchmark comparisons and generate plots.

Options:
    -b, --benchmarks NAMES      Benchmark names (space-separated, default: 010.sleep)
    -p, --platforms PLATFORMS   Platforms to test (space-separated, default: aws)
                                Available: aws azure gcp local
    -l, --languages LANGUAGES   Languages to test (space-separated, default: python)
                                Available: python nodejs rust java pypy
    -c, --config FILE           Configuration file (default: config/example.json)
    -o, --output DIR            Output directory (default: results/comparison_TIMESTAMP)
    -r, --repetitions NUM       Number of repetitions (default: 5)
    -m, --memory SIZES          Memory sizes in MB (space-separated, default: 256)
    -i, --input-size SIZE       Input size: test, small, large (default: test)
    -a, --architecture ARCH     Architecture: x64, arm64 (default: x64)
    --container-deployment      Run functions as containers (all platforms)
    --container-deployment-for  Platforms to use container deployment (space-separated)
                                Example: --container-deployment-for "aws gcp"
    --no-plots                  Skip plot generation
    --skip-benchmark            Skip benchmark run, only generate plots
    -h, --help                  Show this help message

Examples:
    # Compare Python and Node.js on AWS and Azure
    $(basename "$0") -b "010.sleep 110.dynamic-html" -p "aws azure" -l "python nodejs"

    # Compare AWS (container) vs Azure (package deployment)
    $(basename "$0") -b "010.sleep" -p "aws azure" -l "python" --container-deployment-for "aws"

    # Test different memory configurations
    $(basename "$0") -b "501.graph-pagerank" -m "512 1024 2048" -r 10

    # Just generate plots from existing results
    $(basename "$0") --skip-benchmark -o results/comparison_20241212_120000

EOF
}

# Parse arguments
SKIP_BENCHMARK=false
while [[ $# -gt 0 ]]; do
    case $1 in
        -b|--benchmarks)
            BENCHMARKS="$2"
            shift 2
            ;;
        -p|--platforms)
            PLATFORMS="$2"
            shift 2
            ;;
        -l|--languages)
            LANGUAGES="$2"
            shift 2
            ;;
        -c|--config)
            CONFIG="$2"
            shift 2
            ;;
        -o|--output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -r|--repetitions)
            REPETITIONS="$2"
            shift 2
            ;;
        -m|--memory)
            MEMORY="$2"
            shift 2
            ;;
        -i|--input-size)
            INPUT_SIZE="$2"
            shift 2
            ;;
        -a|--architecture)
            ARCHITECTURE="$2"
            shift 2
            ;;
        --container-deployment)
            CONTAINER_DEPLOYMENT=true
            shift
            ;;
        --container-deployment-for)
            CONTAINER_DEPLOYMENT_FOR="$2"
            shift 2
            ;;
        --no-plots)
            GENERATE_PLOTS=false
            shift
            ;;
        --skip-benchmark)
            SKIP_BENCHMARK=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo -e "${RED}Error: Unknown option $1${NC}"
            usage
            exit 1
            ;;
    esac
done

echo "=================================="
echo "Benchmark Comparison Tool"
echo "=================================="
echo ""

# Check if config exists
if [ ! -f "$CONFIG" ]; then
    echo -e "${RED}Error: Configuration file not found: $CONFIG${NC}"
    exit 1
fi

# Run benchmarks unless skipped
if [ "$SKIP_BENCHMARK" = false ]; then
    echo -e "${GREEN}Step 1: Running Benchmarks${NC}"
    echo "  Benchmarks: $BENCHMARKS"
    echo "  Platforms: $PLATFORMS"
    echo "  Languages: $LANGUAGES"
    echo "  Repetitions: $REPETITIONS"
    echo "  Memory: $MEMORY MB"
    echo "  Input Size: $INPUT_SIZE"
    echo "  Architecture: $ARCHITECTURE"
    echo "  Container Deployment: $CONTAINER_DEPLOYMENT"
    if [ -n "$CONTAINER_DEPLOYMENT_FOR" ]; then
        echo "  Container Deployment For: $CONTAINER_DEPLOYMENT_FOR"
    fi
    echo "  Output: $OUTPUT_DIR"
    echo ""
    
    # Build command
    CMD=(
        python3 "${SCRIPT_DIR}/cross_platform_benchmark.py"
        --benchmarks $BENCHMARKS
        --platforms $PLATFORMS
        --languages $LANGUAGES
        --config "$CONFIG"
        --output "$OUTPUT_DIR"
        --repetitions "$REPETITIONS"
        --memory $MEMORY
        --input-size "$INPUT_SIZE"
        --architecture "$ARCHITECTURE"
        --verbose
    )

    if [ "$CONTAINER_DEPLOYMENT" = true ]; then
        CMD+=(--container-deployment)
    fi
    
    if [ -n "$CONTAINER_DEPLOYMENT_FOR" ]; then
        CMD+=(--container-deployment-for $CONTAINER_DEPLOYMENT_FOR)
    fi
    
    # Add --plot flag if plots are enabled (uses integrated plotting)
    if [ "$GENERATE_PLOTS" = true ]; then
        CMD+=(--plot)
    fi
    
    echo "Running: ${CMD[@]}"
    echo ""
    
    if "${CMD[@]}"; then
        echo -e "${GREEN}✓ Benchmarks completed successfully!${NC}"
    else
        echo -e "${RED}✗ Benchmark execution failed!${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}Skipping benchmark execution${NC}"
    
    # Check if results file exists
    if [ ! -f "$OUTPUT_DIR/comparison_results.json" ]; then
        echo -e "${RED}Error: Results file not found: $OUTPUT_DIR/comparison_results.json${NC}"
        exit 1
    fi
    
    # Generate plots from existing results if requested
    if [ "$GENERATE_PLOTS" = true ]; then
        echo ""
        echo -e "${GREEN}Generating Plots from Existing Results${NC}"
        echo ""
        
        PLOT_CMD=(
            python3 "${SCRIPT_DIR}/plot_comparison.py"
            "$OUTPUT_DIR/comparison_results.json"
            --output "$OUTPUT_DIR/plots"
        )
        
        if "${PLOT_CMD[@]}"; then
            echo -e "${GREEN}✓ Plots generated successfully!${NC}"
        else
            echo -e "${YELLOW}⚠ Plot generation failed (may need matplotlib/seaborn)${NC}"
        fi
    fi
fi

echo ""
echo "=================================="
echo -e "${GREEN}Comparison Complete!${NC}"
echo "=================================="
echo ""
echo "Results Location: $OUTPUT_DIR"
echo "  - comparison_results.json  (raw results)"
echo "  - benchmark_run.log        (execution log)"
if [ "$GENERATE_PLOTS" = true ]; then
    echo "  - plots/                   (visualizations)"
fi
echo ""
echo "Useful commands:"
echo "  # Regenerate plots"
echo "  python3 ${SCRIPT_DIR}/plot_comparison.py $OUTPUT_DIR/comparison_results.json"
echo ""
echo "  # Regenerate with specific plot types"
echo "  python3 ${SCRIPT_DIR}/plot_comparison.py $OUTPUT_DIR/comparison_results.json --plot-type cold_warm_boxplot memory_scaling"
echo ""

