# Bitcoin Data Pipeline Documentation

This directory contains comprehensive documentation for the Bitcoin Data Pipeline project.

## 📚 Documentation Overview

### 🏗️ Architecture
Core system design and data flow documentation:
- **[ARCHITECTURE.md](architecture/ARCHITECTURE.md)** - Overall system architecture and design patterns
- **[DATA_PIPELINE.md](architecture/DATA_PIPELINE.md)** - Data flow and processing pipeline details
- **[RELIABILITY.md](architecture/RELIABILITY.md)** - High availability and fault tolerance design

### 🚀 Deployment
Infrastructure and deployment guidance:
- **[AWS_DEPLOYMENT_GUIDE.md](deployment/AWS_DEPLOYMENT_GUIDE.md)** - AWS infrastructure setup and deployment
- **[SERVICES_DEPLOYMENT.md](deployment/SERVICES_DEPLOYMENT.md)** - Service-specific deployment instructions

### 📊 Schemas
Data models and formats:
- **[REDIS_SCHEMA.md](schemas/REDIS_SCHEMA.md)** - Redis data structures and hot state schema
- **[S3_SCHEMA.md](schemas/S3_SCHEMA.md)** - S3 data lake schema and partitioning
- **[RDS_SCHEMA.md](schemas/RDS_SCHEMA.md)** - PostgreSQL database schema for ML training
- **[HYBRID_S3_RDBMS_ANALYSIS.md](schemas/HYBRID_S3_RDBMS_ANALYSIS.md)** - Hybrid storage architecture analysis

### 🔧 Operations
Monitoring, testing, and maintenance:
- **[MONITORING.md](operations/MONITORING.md)** - Monitoring, alerting, and observability
- **[TESTING_GUIDE.md](operations/TESTING_GUIDE.md)** - Testing strategies and procedures

### 👨‍💻 Development
Contributing and development guidance:
- **[CLAUDE.md](development/CLAUDE.md)** - Development guidance for AI assistants
- **[SERVICES_ROADMAP.md](development/SERVICES_ROADMAP.md)** - Service development roadmap and priorities

## 🎯 Quick Navigation

### For New Developers
1. Start with [ARCHITECTURE.md](architecture/ARCHITECTURE.md) to understand the system
2. Review [DATA_PIPELINE.md](architecture/DATA_PIPELINE.md) for data flow details
3. Follow [TESTING_GUIDE.md](operations/TESTING_GUIDE.md) to set up your development environment

### For DevOps Engineers
1. Review [AWS_DEPLOYMENT_GUIDE.md](deployment/AWS_DEPLOYMENT_GUIDE.md) for infrastructure
2. Check [SERVICES_DEPLOYMENT.md](deployment/SERVICES_DEPLOYMENT.md) for service deployment
3. Set up monitoring with [MONITORING.md](operations/MONITORING.md)

### For Data Engineers
1. Understand data flow in [DATA_PIPELINE.md](architecture/DATA_PIPELINE.md)
2. Review schema documentation in [schemas/](schemas/)
3. Check [HYBRID_S3_RDBMS_ANALYSIS.md](schemas/HYBRID_S3_RDBMS_ANALYSIS.md) for storage decisions

### For ML Engineers
1. Start with [RDS_SCHEMA.md](schemas/RDS_SCHEMA.md) for training data structure
2. Review [S3_SCHEMA.md](schemas/S3_SCHEMA.md) for data lake organization
3. Check [SERVICES_ROADMAP.md](development/SERVICES_ROADMAP.md) for ML service priorities

## 📋 Documentation Standards

- **Keep docs up-to-date**: Update documentation when making changes to the system
- **Use clear headings**: Follow markdown best practices for navigation
- **Include examples**: Provide code examples and configuration snippets
- **Link references**: Use relative links between documentation files
- **Add diagrams**: Include architecture diagrams and data flow charts where helpful

## 🤝 Contributing to Documentation

1. **Accuracy**: Ensure all information is current and accurate
2. **Clarity**: Write for the target audience (developers, operators, etc.)
3. **Completeness**: Cover all necessary details without overwhelming
4. **Consistency**: Follow the existing documentation style and structure

## 📁 File Organization

```
docs/
├── README.md                    # This file - documentation index
├── architecture/               # System design and architecture
├── deployment/                 # Infrastructure and deployment
├── schemas/                    # Data models and formats
├── operations/                 # Monitoring, testing, maintenance
└── development/                # Contributing and development guidance
```

For the main project documentation, see the [project README.md](../README.md).