#!/bin/bash
# Convenience wrapper for generating PR annotation cards
#
# Usage:
#   ./scripts/generate_pr_cards.sh [OPTIONS]
#
# Options:
#   --candidates PATH     Path to golden candidates JSON (default: local/quality_runs/<run>/golden_100_candidates.json)
#   --batch PATH          Path to batch results JSON (default: local/quality_runs/<run>/batch_results.json)
#   --cache DIR           Path to PR API cache (default: local/pr_api_cache)
#   --output DIR          Output directory (default: local/golden_cards)
#   --run NAME            Quality run name (sets default paths)
#
# Examples:
#   # Use defaults for latest run
#   ./scripts/generate_pr_cards.sh --run 20260508_precision_fixes
#
#   # Specify all paths explicitly
#   ./scripts/generate_pr_cards.sh \
#       --candidates local/quality_runs/20260508_precision_fixes/golden_100_candidates.json \
#       --batch local/quality_runs/20260508_precision_fixes/batch_results.json \
#       --cache local/pr_api_cache \
#       --output local/golden_cards

set -e

# Default values
RUN_NAME=""
CANDIDATES=""
BATCH_RESULTS=""
CACHE_DIR="local/pr_api_cache"
OUTPUT_DIR="local/golden_cards"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --run)
            RUN_NAME="$2"
            shift 2
            ;;
        --candidates)
            CANDIDATES="$2"
            shift 2
            ;;
        --batch)
            BATCH_RESULTS="$2"
            shift 2
            ;;
        --cache)
            CACHE_DIR="$2"
            shift 2
            ;;
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# Set defaults based on run name
if [[ -n "$RUN_NAME" ]]; then
    BASE_DIR="local/quality_runs/$RUN_NAME"
    if [[ -z "$CANDIDATES" ]]; then
        CANDIDATES="$BASE_DIR/golden_100_candidates.json"
    fi
    if [[ -z "$BATCH_RESULTS" ]]; then
        BATCH_RESULTS="$BASE_DIR/batch_results.json"
    fi
fi

# Validate required arguments
if [[ -z "$CANDIDATES" || -z "$BATCH_RESULTS" ]]; then
    echo "Error: --candidates and --batch are required (or use --run)" >&2
    echo "Usage: $0 --run RUN_NAME [--output DIR]" >&2
    echo "   or: $0 --candidates PATH --batch PATH [--output DIR]" >&2
    exit 1
fi

# Check if files exist
if [[ ! -f "$CANDIDATES" ]]; then
    echo "Error: Candidates file not found: $CANDIDATES" >&2
    exit 1
fi

if [[ ! -f "$BATCH_RESULTS" ]]; then
    echo "Error: Batch results file not found: $BATCH_RESULTS" >&2
    exit 1
fi

# Run the Python script
echo "Generating PR annotation cards..."
echo "  Candidates: $CANDIDATES"
echo "  Batch results: $BATCH_RESULTS"
echo "  Cache: $CACHE_DIR"
echo "  Output: $OUTPUT_DIR"
echo ""

python3 scripts/generate_pr_cards.py \
    --candidates "$CANDIDATES" \
    --batch-results "$BATCH_RESULTS" \
    --pr-api-cache-dir "$CACHE_DIR" \
    --output-dir "$OUTPUT_DIR"
