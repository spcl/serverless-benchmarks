file_name=logs/execution-0.log
counter=0

while [ -e "${file_name}" ]; do
  printf -f file_name -- '%s_%02d.log' "logs/execution" "$(( ++counter ))"
done

script -c 'python3 runner.py input.json' -f "${file_name}"
