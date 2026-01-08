#!/bin/bash
# Wrapper script to run SeBS perf-cost experiment and generate plots in one command

set -e  # Exit on error

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Run SeBS perf-cost experiment and automatically generate plots.

Required Options:
    --config CONFIG           Path to SeBS config file
    --deployment PLATFORM     Deployment platform (aws, azure, gcp)
    --output-dir DIR          Output directory for measurements

Optional Options:
    --benchmark-name NAME     Benchmark name for plot titles (e.g., "110.html")
    --language-name LANG      Language name for plot titles (e.g., "Python 3.11")
    --title-comment TEXT      Additional comment for titles (e.g., "codepackage", "-O2")
    --skip-invoke            Skip the invoke step (only process existing data)
    --skip-process           Skip the process step (only invoke)
    --update-code            Update function code before running
    --help                   Show this help message

Examples:
    # Run full workflow (invoke + process + plot)
    $0 --config config/aws_110_html_python_128_512_2048.json \\
       --deployment aws \\
       --output-dir measurements/110-html-python \\
       --benchmark-name "110.html" \\
       --language-name "Python 3.11" \\
       --title-comment "codepackage"

    # Just process existing data and plot
    $0 --config config/aws_110_html_cpp.json \\
       --deployment aws \\
       --output-dir measurements/110-html-cpp \\
       --benchmark-name "110.html" \\
       --language-name "C++ -O2" \\
       --skip-invoke

EOF
    exit 1
}

# Default values
SKIP_INVOKE=false
SKIP_PROCESS=false
UPDATE_CODE=""
BENCHMARK_NAME=""
LANGUAGE_NAME=""
TITLE_COMMENT=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --config)
            CONFIG="$2"
            shift 2
            ;;
        --deployment)
            DEPLOYMENT="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --benchmark-name)
            BENCHMARK_NAME="$2"
            shift 2
            ;;
        --language-name)
            LANGUAGE_NAME="$2"
            shift 2
            ;;
        --title-comment)
            TITLE_COMMENT="$2"
            shift 2
            ;;
        --skip-invoke)
            SKIP_INVOKE=true
            shift
            ;;
        --skip-process)
            SKIP_PROCESS=true
            shift
            ;;
        --update-code)
            UPDATE_CODE="--update-code"
            shift
            ;;
        --help)
            usage
            ;;
        *)
            echo -e "${RED}Error: Unknown option $1${NC}"
            usage
            ;;
    esac
done

# Validate required arguments
if [[ -z "$CONFIG" ]] || [[ -z "$DEPLOYMENT" ]] || [[ -z "$OUTPUT_DIR" ]]; then
    echo -e "${RED}Error: Missing required arguments${NC}"
    usage
fi

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}SeBS Perf-Cost Experiment with Plots${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo -e "Config:      ${GREEN}$CONFIG${NC}"
echo -e "Deployment:  ${GREEN}$DEPLOYMENT${NC}"
echo -e "Output:      ${GREEN}$OUTPUT_DIR${NC}"
echo ""

# Step 1: Invoke experiment
if [[ "$SKIP_INVOKE" == false ]]; then
    echo -e "${YELLOW}Step 1: Running experiment (invoke perf-cost)...${NC}"
    cd "$PROJECT_ROOT"
    ./sebs.py experiment invoke perf-cost \
        --config "$CONFIG" \
        --deployment "$DEPLOYMENT" \
        --output-dir "$OUTPUT_DIR" \
        $UPDATE_CODE
    
    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}✓ Experiment completed successfully${NC}"
    else
        echo -e "${RED}✗ Experiment failed${NC}"
        exit 1
    fi
    echo ""
else
    echo -e "${YELLOW}Step 1: Skipping invoke step${NC}"
    echo ""
fi

# Step 2: Process experiment
if [[ "$SKIP_PROCESS" == false ]]; then
    echo -e "${YELLOW}Step 2: Processing results...${NC}"
    cd "$PROJECT_ROOT"
    ./sebs.py experiment process perf-cost \
        --config "$CONFIG" \
        --deployment "$DEPLOYMENT" \
        --output-dir "$OUTPUT_DIR"
    
    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}✓ Processing completed successfully${NC}"
    else
        echo -e "${RED}✗ Processing failed${NC}"
        exit 1
    fi
    echo ""
else
    echo -e "${YELLOW}Step 2: Skipping process step${NC}"
    echo ""
fi

# Step 3: Generate plots
echo -e "${YELLOW}Step 3: Generating plots...${NC}"

CSV_FILE="$OUTPUT_DIR/perf-cost/result.csv"

if [[ ! -f "$CSV_FILE" ]]; then
    echo -e "${RED}✗ CSV file not found: $CSV_FILE${NC}"
    echo -e "${RED}  Make sure the process step completed successfully${NC}"
    exit 1
fi

# Build plot command
PLOT_CMD="python3 $SCRIPT_DIR/plot_comparison.py $CSV_FILE --plot-type sebs"

if [[ -n "$BENCHMARK_NAME" ]]; then
    PLOT_CMD="$PLOT_CMD --benchmark-name \"$BENCHMARK_NAME\""
fi

if [[ -n "$LANGUAGE_NAME" ]]; then
    PLOT_CMD="$PLOT_CMD --language-name \"$LANGUAGE_NAME\""
fi

if [[ -n "$TITLE_COMMENT" ]]; then
    PLOT_CMD="$PLOT_CMD --title-comment \"$TITLE_COMMENT\""
fi

eval $PLOT_CMD

if [[ $? -eq 0 ]]; then
    echo -e "${GREEN}✓ Plots generated successfully${NC}"
    echo -e "${GREEN}  Output: $OUTPUT_DIR/perf-cost/plots/${NC}"
else
    echo -e "${RED}✗ Plot generation failed${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}======================================${NC}"
echo -e "${GREEN}✓ All steps completed successfully!${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo -e "Results:"
echo -e "  CSV:   ${GREEN}$CSV_FILE${NC}"
echo -e "  Plots: ${GREEN}$OUTPUT_DIR/perf-cost/plots/${NC}"
echo ""

