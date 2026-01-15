#!/bin/bash
# Run scalability tests levels 1-4 with real OpenAI calls

set -e

echo "=========================================="
echo "Running Real-World Scalability Tests"
echo "Levels 1-4 with REAL OpenAI API calls"
echo "=========================================="
echo ""

cd /app

for level in 1 2 3 4; do
    echo ""
    echo "=========================================="
    echo "Starting Level $level Test"
    echo "=========================================="
    echo ""
    
    python3 manage.py test tests.test_scalability_levels.TestIndividualLevels.test_level_$level --keepdb --verbosity=2 2>&1 | tee /tmp/level_${level}_results.log
    
    echo ""
    echo "Level $level completed. Results saved to /tmp/level_${level}_results.log"
    echo ""
done

echo ""
echo "=========================================="
echo "All tests completed!"
echo "=========================================="
