LOG_STREAM=$(aws batch describe-jobs --region us-east-2 \
  --jobs "290f4a44-c654-49b4-9fde-6f140548bf80:0" \
  --query 'jobs[0].container.logStreamName' \
  --output text)

aws logs get-log-events --region us-east-2 \
  --log-group-name /aws/batch/job \
  --log-stream-name "$LOG_STREAM" \
  --query 'events[*].message' \
  --output text)
