#!/bin/bash

echo "🚀 Starting deployment process for University EMS Schedule Service..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if .env file exists
if [ ! -f .env ]; then
    print_error ".env file not found! Please create one based on .env.example"
    exit 1
fi

# Clean up previous builds
print_status "Cleaning up previous builds..."
rm -rf .serverless
rm -rf node_modules/.cache

# Install serverless plugins if not already installed
print_status "Installing serverless plugins..."
npm install --save-dev serverless-python-requirements serverless-offline serverless-dotenv-plugin

# Check if AWS credentials are configured
print_status "Checking AWS credentials..."
if ! aws sts get-caller-identity &> /dev/null; then
    print_error "AWS credentials not configured! Please run 'aws configure' first."
    exit 1
fi

# Deploy to AWS
print_status "Deploying to AWS Lambda..."
if serverless deploy --verbose; then
    print_status "✅ Deployment completed successfully!"
    print_status "API Gateway URL will be shown above"
else
    print_error "❌ Deployment failed!"
    exit 1
fi 