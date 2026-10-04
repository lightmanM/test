#!/usr/bin/env bash
# Create the demo's server on AWS (EC2, Ubuntu 24.04), or show the existing one. Safe to re-run;
# each run also allows SSH from this machine's current IP.
#   AWS_PROFILE=pond-new deploy/aws/provision.sh
# Everything is named and tagged "workflow-demo": an SSH key pair (private key in
# ~/.ssh/workflow-demo.pem), a security group (HTTP/HTTPS from anywhere, SSH from this machine),
# the instance and an Elastic IP, so the address and the sslip.io hostnames survive a stop/start.
set -euo pipefail

NAME=workflow-demo
export AWS_PROFILE=${AWS_PROFILE:-pond-new}
export AWS_REGION=${AWS_REGION:-us-west-2}  # pond-new's us-east-2 has no free vCPU quota
INSTANCE_TYPE=${INSTANCE_TYPE:-t3.large}
DISK_GB=${DISK_GB:-40}
KEY_FILE="$HOME/.ssh/$NAME.pem"
HERE="$(cd "$(dirname "$0")" && pwd)"
TAGS="{Key=Name,Value=$NAME},{Key=Project,Value=$NAME}"
UBUNTU_AMI_PARAM=/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id

text() { aws "$@" --output text; }

# SSH key pair (key pairs are per region: an existing local key is imported, not replaced)
if ! aws ec2 describe-key-pairs --key-names "$NAME" >/dev/null 2>&1; then
  if [ -e "$KEY_FILE" ]; then
    PUB=$(mktemp)
    ssh-keygen -y -f "$KEY_FILE" >"$PUB"
    aws ec2 import-key-pair --key-name "$NAME" --public-key-material "fileb://$PUB" \
      --tag-specifications "ResourceType=key-pair,Tags=[$TAGS]" >/dev/null
    rm -f "$PUB"
    echo "Imported $KEY_FILE as key pair $NAME"
  else
    (umask 077 && text ec2 create-key-pair --key-name "$NAME" --key-type ed25519 \
      --tag-specifications "ResourceType=key-pair,Tags=[$TAGS]" --query KeyMaterial >"$KEY_FILE")
    echo "Created key pair $NAME (key file: $KEY_FILE)"
  fi
fi

# Security group in the default VPC
VPC=$(text ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId')
SG=$(text ec2 describe-security-groups --filters "Name=group-name,Values=$NAME" "Name=vpc-id,Values=$VPC" \
  --query 'SecurityGroups[0].GroupId')
if [ "$SG" = None ]; then
  SG=$(text ec2 create-security-group --group-name "$NAME" --description "Workflow demo server" \
    --vpc-id "$VPC" --tag-specifications "ResourceType=security-group,Tags=[$TAGS]" --query GroupId)
  for port in 80 443; do
    aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port "$port" --cidr 0.0.0.0/0 >/dev/null
  done
  aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol udp --port 443 --cidr 0.0.0.0/0 >/dev/null
  echo "Created security group $SG"
fi
MY_IP=$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')
# SSH only from this machine: drop rules for addresses used before (they may belong to others now).
for cidr in $(text ec2 describe-security-groups --group-ids "$SG" \
  --query 'SecurityGroups[0].IpPermissions[?FromPort==`22`].IpRanges[].CidrIp'); do
  if [ "$cidr" != "$MY_IP/32" ]; then
    aws ec2 revoke-security-group-ingress --group-id "$SG" --protocol tcp --port 22 --cidr "$cidr" >/dev/null
    echo "Removed SSH access from $cidr"
  fi
done
if aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 22 --cidr "$MY_IP/32" >/dev/null 2>&1; then
  echo "Allowed SSH from $MY_IP"
fi

# Instance
ID=$(text ec2 describe-instances --filters "Name=tag:Name,Values=$NAME" \
  "Name=instance-state-name,Values=pending,running,stopping,stopped" --query 'Reservations[0].Instances[0].InstanceId')
if [ "$ID" = None ]; then
  AMI=$(text ssm get-parameter --name "$UBUNTU_AMI_PARAM" --query Parameter.Value)
  ID=$(text ec2 run-instances --image-id "$AMI" --instance-type "$INSTANCE_TYPE" --key-name "$NAME" \
    --security-group-ids "$SG" --metadata-options HttpTokens=required \
    --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISK_GB,VolumeType=gp3,Encrypted=true}" \
    --user-data "file://$HERE/cloud-init.yaml" \
    --tag-specifications "ResourceType=instance,Tags=[$TAGS]" "ResourceType=volume,Tags=[$TAGS]" \
    --query 'Instances[0].InstanceId')
  echo "Launched $ID ($INSTANCE_TYPE, Ubuntu 24.04, ${DISK_GB} GB); first boot installs Docker"
fi
aws ec2 wait instance-running --instance-ids "$ID"

# Elastic IP
ALLOC=$(text ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME" --query 'Addresses[0].AllocationId')
if [ "$ALLOC" = None ]; then
  ALLOC=$(text ec2 allocate-address --domain vpc --tag-specifications "ResourceType=elastic-ip,Tags=[$TAGS]" \
    --query AllocationId)
fi
aws ec2 associate-address --instance-id "$ID" --allocation-id "$ALLOC" >/dev/null
IP=$(text ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].PublicIp')
DASHED=${IP//./-}

cat <<EOF

Server $ID is running at $IP. For deploy/aws/.env:
SERVER_IP=$IP
DEMO_HOST=demo-$DASHED.sslip.io
N8N_HOST=n8n-$DASHED.sslip.io

SSH: ssh -i $KEY_FILE ubuntu@$IP
EOF
