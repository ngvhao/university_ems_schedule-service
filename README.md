# University EMS Schedule Service

Serverless FastAPI application for university schedule management deployed on AWS Lambda.

## Project Structure

```
university_ems_schedule-service/
├── app/
│   ├── main.py                 # FastAPI application entry point
│   ├── database.py             # Database configuration
│   ├── middleware/             # Custom middleware
│   ├── models/                 # SQLAlchemy models
│   ├── routes/                 # API routes
│   ├── services/               # Business logic services
│   └── utils/                  # Utility functions
├── serverless.yml              # Serverless Framework configuration
├── requirements.txt            # Python dependencies
├── package.json               # Node.js dependencies
└── deploy.sh                  # Deployment script
```

## Prerequisites

- Node.js (v16 or higher)
- Python 3.9
- AWS CLI configured with appropriate credentials
- PostgreSQL database

## Environment Variables

Create a `.env` file with the following variables:

```env
# Serverless Configuration
STAGE=dev
DEBUG=0

# Database Configuration
DB_HOST=your-database-host
DB_PORT=5432
DB_USER_NAME=your-database-username
DB_PASSWORD=your-database-password
DB_NAME=your-database-name

# JWT Configuration
JWT_SECRET_KEY=your-jwt-secret-key-here
```

## Installation

1. Install Node.js dependencies:

```bash
npm install
```

2. Install Python dependencies (optional for local development):

```bash
pip install -r requirements.txt
```

## Deployment

### Quick Deploy

```bash
./deploy.sh
```

### Manual Deploy

```bash
serverless deploy
```

### Deploy to Production

```bash
STAGE=prod serverless deploy
```

## Local Development

Start the serverless offline server:

```bash
serverless offline
```

The API will be available at `http://localhost:3000`

## API Endpoints

- `GET /health` - Health check
- `GET /testing-db` - Database connection test
- `GET /docs` - API documentation (Swagger UI)
- `POST /schedules/calculating` - Calculate schedule

## Configuration

### Serverless.yml Features

- **Memory**: 512MB (configurable)
- **Timeout**: 30 seconds (configurable)
- **Runtime**: Python 3.9
- **Region**: ap-southeast-1
- **CORS**: Enabled
- **Logging**: CloudWatch with 14-day retention

### Python Requirements

- FastAPI 0.104.1
- Mangum 0.17.0 (Lambda adapter)
- SQLAlchemy 1.4.53
- AsyncPG 0.29.0
- Pydantic 1.10.13

## Troubleshooting

### Common Issues

1. **Dependency Installation Errors**

   - Ensure you're using Python 3.9
   - Try clearing cache: `rm -rf .serverless/cache`

2. **Database Connection Issues**

   - Verify database credentials in `.env`
   - Ensure database is accessible from Lambda VPC

3. **Deployment Failures**
   - Check AWS credentials
   - Verify IAM permissions
   - Check CloudWatch logs for errors

## Monitoring

- **CloudWatch Logs**: `/aws/lambda/university-ems-schedule-service-{stage}`
- **API Gateway**: Monitor API usage and errors
- **Lambda Metrics**: Monitor function performance

## Security

- JWT authentication middleware
- Environment variable encryption
- IAM role with minimal permissions
- CORS configuration
