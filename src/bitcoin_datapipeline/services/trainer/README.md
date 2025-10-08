# Bitcoin Trainer Service - S3 Gold Layer Training Pipeline

## Overview

The Bitcoin Trainer Service implements the **machine learning training pipeline** for the 10-second ahead Bitcoin price prediction system. It processes S3 gold layer data to train lightweight MLP models optimized for **sub-100ms inference** while maintaining prediction accuracy for real-time deployment.

## Architecture Philosophy

- **S3 Gold Layer Focus**: Train exclusively on processed feature vectors and labels
- **Inference-Optimized Models**: Design models for <100ms inference latency
- **Continuous Learning**: Automated daily training with performance monitoring
- **Model Versioning**: Systematic model deployment with rollback capabilities
- **Feature Engineering**: Advanced feature selection for 10-second prediction horizon

## Training Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRAINING PIPELINE                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  S3 Gold Layer ──► Feature Engineering ──► Model Training      │
│  (2s features,  │  (selection,          │  (lightweight MLP,  │
│   10s labels)   │   validation)         │   <100ms inference) │
│                 │                       │                      │
│                 ▼                       ▼                      │
│           ┌──────────────┐        ┌──────────────┐             │
│           │Time Series   │        │Model         │             │
│           │Validation    │        │Optimization  │             │
│           │& Splits      │        │& Export      │             │
│           └──────────────┘        └──────────────┘             │
│                 │                       │                      │
│                 ▼                       ▼                      │
│           ┌──────────────┐        ┌──────────────┐             │
│           │Training      │        │Performance   │             │
│           │Datasets      │        │Validation    │             │
│           │              │        │& Deployment  │             │
│           └──────────────┘        └──────────────┘             │
└─────────────────────────────────────────────────────────────────┘
                                   │
┌─────────────────────────────────────────────────────────────────┐
│                    MODEL DEPLOYMENT                            │
├─────────────────────────────────────────────────────────────────┤
│                                   │                             │
│  Model Registry ──► Version Control ──► Inference Deployment   │
│  (ONNX models,   │  (A/B testing,     │  (ECS hot reload,     │
│   metadata)      │   rollback)        │   zero downtime)      │
│                  │                    │                       │
│                  ▼                    ▼                       │
│            ┌──────────────┐     ┌──────────────┐              │
│            │Model         │     │Performance   │              │
│            │Validation    │     │Monitoring    │              │
│            │& Testing     │     │& Alerts      │              │
│            └──────────────┘     └──────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export AWS_REGION="us-east-1"
export S3_BUCKET="bitcoin-data-lake"
export MODEL_REGISTRY_BUCKET="bitcoin-models"
```

### Local Development

1. **Start Infrastructure**:
```bash
cd ../../  # Project root
docker-compose up localstack -d
```

2. **Run Training Pipeline**:
```bash
CONFIG_FILE=config/local.yaml python src/main.py --mode train
```

3. **Model Evaluation**:
```bash
CONFIG_FILE=config/local.yaml python src/main.py --mode evaluate
```

### Production Deployment

```bash
# Build and deploy
docker build -t bitcoin-trainer .

# Daily training job
docker run --rm \
  -e CONFIG_FILE=config/prod.yaml \
  -e AWS_REGION=${AWS_REGION} \
  -e S3_BUCKET=${S3_BUCKET} \
  bitcoin-trainer --mode train

# Model deployment
docker run --rm \
  -e CONFIG_FILE=config/prod.yaml \
  bitcoin-trainer --mode deploy
```

## Configuration

### Training Configuration (`config/training.yaml`)
```yaml
service_name: "bitcoin-trainer"

data:
  s3_bucket: "bitcoin-data-lake"
  gold_prefix: "gold"
  features_path: "features_2s/BTCUSDT"
  labels_path: "labels_10s/BTCUSDT"
  lookback_days: 30              # Training data window
  validation_days: 7             # Validation period
  
training:
  prediction_horizon_seconds: 10  # Target: 10 seconds ahead
  feature_window_seconds: 2       # Feature frequency
  batch_size: 1024
  learning_rate: 0.001
  epochs: 100
  early_stopping_patience: 10
  validation_split: 0.2
  
model:
  architecture: "mlp"
  hidden_layers: [128, 64, 32, 16]
  dropout_rate: 0.2
  activation: "relu"
  output_activation: "linear"
  l2_regularization: 0.001
  inference_target_ms: 30        # <30ms inference requirement
  
features:
  price_features: ["price", "mid_price", "ret_1s", "ret_5s", "ret_10s"]
  volume_features: ["volume_1s", "volume_5s", "vol_imbalance_1s", "vol_imbalance_5s"]
  orderbook_features: ["spread_bp", "ob_imbalance", "bid_strength", "ask_strength"]
  trade_features: ["trade_intensity_1s", "avg_trade_size_1s", "dollar_volume_1s"]
  technical_features: ["vwap_dev_1s", "vwap_dev_5s", "price_volatility", "momentum"]
  
validation:
  min_accuracy_threshold: 0.55    # Minimum directional accuracy
  max_mae_threshold: 50.0         # Maximum mean absolute error
  min_correlation: 0.3            # Minimum prediction correlation
  confidence_calibration: true    # Validate confidence scores
  
deployment:
  model_registry_bucket: "bitcoin-models"
  model_format: "onnx"            # Optimized for inference
  auto_deploy: false              # Require manual approval
  a_b_testing: true               # Gradual rollout
  rollback_on_degradation: true   # Auto-rollback if performance drops

health:
  port: 8084
  host: "0.0.0.0"
```

## S3 Gold Layer Data Processing

### 1. Feature Data Loading

#### S3 Feature Vector Processing
```python
class GoldLayerDataLoader:
    def __init__(self, s3_bucket: str, config: dict):
        self.s3_bucket = s3_bucket
        self.config = config
        self.s3_client = boto3.client('s3')
    
    async def load_training_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Load feature vectors and labels from S3 gold layer"""
        
        # Load feature vectors
        features_df = await self.load_feature_vectors(start_date, end_date)
        
        # Load labels
        labels_df = await self.load_labels(start_date, end_date)
        
        # Align features and labels by timestamp
        training_data = self.align_features_labels(features_df, labels_df)
        
        return training_data
    
    async def load_feature_vectors(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Load feature vectors from S3 gold layer"""
        
        feature_files = []
        current_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_date_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        # List all feature files in date range
        while current_date <= end_date_dt:
            prefix = f"gold/features_2s/BTCUSDT/year={current_date.year}/month={current_date.month:02d}/day={current_date.day:02d}/"
            
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.s3_bucket, Prefix=prefix)
            
            for page in pages:
                for obj in page.get('Contents', []):
                    if obj['Key'].endswith('.parquet'):
                        feature_files.append(obj['Key'])
            
            current_date += timedelta(days=1)
        
        # Load and combine all feature files
        feature_dfs = []
        for file_key in feature_files:
            df = pd.read_parquet(f"s3://{self.s3_bucket}/{file_key}")
            feature_dfs.append(df)
        
        combined_features = pd.concat(feature_dfs, ignore_index=True)
        combined_features = combined_features.sort_values('ts').reset_index(drop=True)
        
        logger.info(f"Loaded {len(combined_features)} feature vectors from {len(feature_files)} files")
        return combined_features
    
    async def load_labels(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Load 10-second ahead labels from S3 gold layer"""
        
        label_files = []
        current_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_date_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        while current_date <= end_date_dt:
            prefix = f"gold/labels_10s/BTCUSDT/year={current_date.year}/month={current_date.month:02d}/day={current_date.day:02d}/"
            
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.s3_bucket, Prefix=prefix)
            
            for page in pages:
                for obj in page.get('Contents', []):
                    if obj['Key'].endswith('.parquet'):
                        label_files.append(obj['Key'])
            
            current_date += timedelta(days=1)
        
        # Load and combine all label files
        label_dfs = []
        for file_key in label_files:
            df = pd.read_parquet(f"s3://{self.s3_bucket}/{file_key}")
            label_dfs.append(df)
        
        combined_labels = pd.concat(label_dfs, ignore_index=True)
        combined_labels = combined_labels.sort_values('feature_ts').reset_index(drop=True)
        
        logger.info(f"Loaded {len(combined_labels)} labels from {len(label_files)} files")
        return combined_labels
```

### 2. Data Validation and Preprocessing

#### Feature Quality Validation
```python
class DataValidator:
    def __init__(self, config: dict):
        self.config = config
    
    def validate_training_data(self, data: pd.DataFrame) -> pd.DataFrame:
        """Validate and clean training data"""
        
        initial_rows = len(data)
        
        # 1. Remove rows with missing target values
        data = data.dropna(subset=['target_price', 'return_10s'])
        
        # 2. Remove rows with invalid timestamps
        data = data[data['feature_ts'] > 0]
        data = data[data['target_ts'] > data['feature_ts']]
        
        # 3. Remove extreme outliers
        data = self.remove_price_outliers(data)
        
        # 4. Validate feature completeness
        data = data[data['completeness'] >= 0.8]  # Require 80% feature completeness
        
        # 5. Remove data during market closures or extreme events
        data = self.filter_market_conditions(data)
        
        final_rows = len(data)
        logger.info(f"Data validation: {initial_rows} → {final_rows} rows ({(final_rows/initial_rows)*100:.1f}% retained)")
        
        return data
    
    def remove_price_outliers(self, data: pd.DataFrame) -> pd.DataFrame:
        """Remove extreme price movements that may be data errors"""
        
        # Remove 10-second returns >±5% (likely errors)
        data = data[abs(data['return_10s']) <= 0.05]
        
        # Remove prices outside reasonable range
        price_median = data['current_price'].median()
        data = data[data['current_price'].between(
            price_median * 0.5, price_median * 2.0
        )]
        
        return data
    
    def filter_market_conditions(self, data: pd.DataFrame) -> pd.DataFrame:
        """Filter out data during extreme market conditions"""
        
        # Remove high volatility periods (>1% in 1 second)
        data = data[data['price_volatility'] <= 0.01]
        
        # Remove very wide spreads (>50 basis points)
        data = data[data['spread_bp'] <= 50]
        
        # Remove very low volume periods
        volume_threshold = data['volume_1s'].quantile(0.05)
        data = data[data['volume_1s'] >= volume_threshold]
        
        return data
```

### 3. Feature Engineering

#### Advanced Feature Creation
```python
class FeatureEngineer:
    def __init__(self, config: dict):
        self.config = config
        self.feature_columns = self._get_feature_columns()
    
    def engineer_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Create additional features for 10-second prediction"""
        
        # 1. Price momentum features
        data = self.add_momentum_features(data)
        
        # 2. Volume profile features
        data = self.add_volume_features(data)
        
        # 3. Orderbook strength features
        data = self.add_orderbook_features(data)
        
        # 4. Time-based features
        data = self.add_temporal_features(data)
        
        # 5. Interaction features
        data = self.add_interaction_features(data)
        
        return data
    
    def add_momentum_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Add price momentum and acceleration features"""
        
        # Price acceleration (change in momentum)
        data['price_acceleration'] = data['ret_5s'] - data['ret_1s']
        
        # Volume-weighted momentum
        data['volume_momentum'] = data['momentum'] * data['volume_1s']
        
        # Volatility-adjusted returns
        data['vol_adj_ret_1s'] = data['ret_1s'] / (data['price_volatility'] + 1e-6)
        data['vol_adj_ret_5s'] = data['ret_5s'] / (data['price_volatility'] + 1e-6)
        
        return data
    
    def add_volume_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Add volume profile and flow features"""
        
        # Volume rate of change
        data['volume_change_5s'] = (data['volume_5s'] - data['volume_1s'] * 5) / (data['volume_1s'] * 5 + 1e-6)
        
        # Dollar volume intensity
        data['dollar_intensity'] = data['dollar_volume_1s'] / data['price']
        
        # Trade size momentum
        data['trade_size_trend'] = data['avg_trade_size_1s'] - data['volume_5s'] / (data['trade_intensity_1s'] * 5 + 1e-6)
        
        return data
    
    def add_orderbook_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Add order book depth and imbalance features"""
        
        # Spread-adjusted imbalance
        data['spread_adj_imbalance'] = data['ob_imbalance'] / (data['spread_bp'] + 1e-6)
        
        # Relative bid/ask strength
        data['bid_ask_ratio'] = data['bid_strength'] / (data['ask_strength'] + 1e-6)
        
        # Weighted mid price vs last price
        data['mid_last_diff'] = (data['mid_price'] - data['price']) / data['price']
        
        return data
    
    def add_temporal_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Add time-based features"""
        
        # Convert timestamp to datetime
        data['datetime'] = pd.to_datetime(data['feature_ts'], unit='s')
        
        # Hour of day (market microstructure)
        data['hour'] = data['datetime'].dt.hour
        data['hour_sin'] = np.sin(2 * np.pi * data['hour'] / 24)
        data['hour_cos'] = np.cos(2 * np.pi * data['hour'] / 24)
        
        # Market session indicators
        data['is_us_hours'] = ((data['hour'] >= 9) & (data['hour'] <= 16)).astype(int)
        data['is_asia_hours'] = ((data['hour'] >= 0) & (data['hour'] <= 8)).astype(int)
        
        return data
    
    def add_interaction_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Add interaction features between different domains"""
        
        # Price-volume interactions
        data['price_volume_int'] = data['ret_1s'] * data['vol_imbalance_1s']
        
        # Spread-momentum interactions
        data['spread_momentum_int'] = data['spread_bp'] * data['momentum']
        
        # Volatility-imbalance interactions
        data['vol_imbalance_int'] = data['price_volatility'] * data['ob_imbalance']
        
        return data
    
    def _get_feature_columns(self) -> List[str]:
        """Get list of feature columns for model training"""
        
        base_features = (
            self.config['features']['price_features'] +
            self.config['features']['volume_features'] +
            self.config['features']['orderbook_features'] +
            self.config['features']['trade_features'] +
            self.config['features']['technical_features']
        )
        
        # Add engineered features
        engineered_features = [
            'price_acceleration', 'volume_momentum', 'vol_adj_ret_1s', 'vol_adj_ret_5s',
            'volume_change_5s', 'dollar_intensity', 'trade_size_trend',
            'spread_adj_imbalance', 'bid_ask_ratio', 'mid_last_diff',
            'hour_sin', 'hour_cos', 'is_us_hours', 'is_asia_hours',
            'price_volume_int', 'spread_momentum_int', 'vol_imbalance_int'
        ]
        
        return base_features + engineered_features
```

## Model Training Pipeline

### 1. Time Series Data Splitting

#### Temporal Validation Strategy
```python
class TimeSeriesValidator:
    def __init__(self, config: dict):
        self.config = config
    
    def create_temporal_splits(self, data: pd.DataFrame) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """Create time-based train/validation splits"""
        
        data = data.sort_values('feature_ts').reset_index(drop=True)
        
        # Walk-forward validation
        validation_days = self.config['data']['validation_days']
        total_days = (data['feature_ts'].max() - data['feature_ts'].min()) / (24 * 3600)
        
        splits = []
        
        # Use last validation_days for final validation
        split_timestamp = data['feature_ts'].max() - (validation_days * 24 * 3600)
        
        train_data = data[data['feature_ts'] < split_timestamp]
        val_data = data[data['feature_ts'] >= split_timestamp]
        
        splits.append((train_data, val_data))
        
        logger.info(f"Created temporal split: {len(train_data)} train, {len(val_data)} validation")
        
        return splits
    
    def create_walk_forward_splits(self, data: pd.DataFrame, n_splits: int = 5) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """Create multiple walk-forward validation splits"""
        
        data = data.sort_values('feature_ts').reset_index(drop=True)
        splits = []
        
        total_samples = len(data)
        test_size = total_samples // (n_splits + 1)
        
        for i in range(n_splits):
            train_end = total_samples - (n_splits - i) * test_size
            val_start = train_end
            val_end = train_end + test_size
            
            train_data = data.iloc[:train_end]
            val_data = data.iloc[val_start:val_end]
            
            splits.append((train_data, val_data))
        
        return splits
```

### 2. Lightweight MLP Model

#### Inference-Optimized Architecture
```python
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

class BitcoinPriceMLP(nn.Module):
    def __init__(self, input_size: int, hidden_layers: List[int], dropout_rate: float = 0.2):
        super(BitcoinPriceMLP, self).__init__()
        
        self.input_size = input_size
        self.hidden_layers = hidden_layers
        
        layers = []
        prev_size = input_size
        
        # Hidden layers with batch norm and dropout
        for hidden_size in hidden_layers:
            layers.extend([
                nn.Linear(prev_size, hidden_size),
                nn.BatchNorm1d(hidden_size),
                nn.ReLU(),
                nn.Dropout(dropout_rate)
            ])
            prev_size = hidden_size
        
        # Output layer (single price prediction)
        layers.append(nn.Linear(prev_size, 1))
        
        self.network = nn.Sequential(*layers)
        
        # Initialize weights for faster convergence
        self._initialize_weights()
    
    def forward(self, x):
        return self.network(x)
    
    def _initialize_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.constant_(m.bias, 0)

class ModelTrainer:
    def __init__(self, config: dict):
        self.config = config
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
    def train_model(self, train_data: pd.DataFrame, val_data: pd.DataFrame) -> BitcoinPriceMLP:
        """Train MLP model for 10-second price prediction"""
        
        # Prepare data
        feature_columns = self._get_feature_columns()
        X_train = train_data[feature_columns].values.astype(np.float32)
        y_train = train_data['target_price'].values.astype(np.float32)
        
        X_val = val_data[feature_columns].values.astype(np.float32)
        y_val = val_data['target_price'].values.astype(np.float32)
        
        # Normalize features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_val_scaled = scaler.transform(X_val)
        
        # Create data loaders
        train_dataset = TensorDataset(
            torch.tensor(X_train_scaled), 
            torch.tensor(y_train)
        )
        val_dataset = TensorDataset(
            torch.tensor(X_val_scaled), 
            torch.tensor(y_val)
        )
        
        train_loader = DataLoader(
            train_dataset, 
            batch_size=self.config['training']['batch_size'], 
            shuffle=True
        )
        val_loader = DataLoader(
            val_dataset, 
            batch_size=self.config['training']['batch_size'], 
            shuffle=False
        )
        
        # Initialize model
        model = BitcoinPriceMLP(
            input_size=len(feature_columns),
            hidden_layers=self.config['model']['hidden_layers'],
            dropout_rate=self.config['model']['dropout_rate']
        ).to(self.device)
        
        # Training setup
        criterion = nn.MSELoss()
        optimizer = optim.Adam(
            model.parameters(), 
            lr=self.config['training']['learning_rate'],
            weight_decay=self.config['model']['l2_regularization']
        )
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode='min', patience=5, factor=0.5
        )
        
        # Training loop
        best_val_loss = float('inf')
        patience_counter = 0
        
        for epoch in range(self.config['training']['epochs']):
            # Training
            model.train()
            train_loss = 0.0
            
            for batch_X, batch_y in train_loader:
                batch_X, batch_y = batch_X.to(self.device), batch_y.to(self.device)
                
                optimizer.zero_grad()
                outputs = model(batch_X).squeeze()
                loss = criterion(outputs, batch_y)
                loss.backward()
                optimizer.step()
                
                train_loss += loss.item()
            
            # Validation
            model.eval()
            val_loss = 0.0
            
            with torch.no_grad():
                for batch_X, batch_y in val_loader:
                    batch_X, batch_y = batch_X.to(self.device), batch_y.to(self.device)
                    outputs = model(batch_X).squeeze()
                    loss = criterion(outputs, batch_y)
                    val_loss += loss.item()
            
            train_loss /= len(train_loader)
            val_loss /= len(val_loader)
            
            scheduler.step(val_loss)
            
            # Early stopping
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                # Save best model
                torch.save(model.state_dict(), 'best_model.pth')
            else:
                patience_counter += 1
                
            if patience_counter >= self.config['training']['early_stopping_patience']:
                logger.info(f"Early stopping at epoch {epoch}")
                break
            
            if epoch % 10 == 0:
                logger.info(f"Epoch {epoch}: Train Loss: {train_loss:.6f}, Val Loss: {val_loss:.6f}")
        
        # Load best model
        model.load_state_dict(torch.load('best_model.pth'))
        
        return model, scaler
```

### 3. Model Export and Optimization

#### ONNX Export for Inference
```python
class ModelExporter:
    def __init__(self, config: dict):
        self.config = config
    
    def export_to_onnx(self, model: BitcoinPriceMLP, scaler: StandardScaler, 
                       sample_input: np.ndarray) -> str:
        """Export trained model to ONNX format for optimized inference"""
        
        model.eval()
        
        # Convert sample input to tensor
        dummy_input = torch.tensor(
            scaler.transform(sample_input.reshape(1, -1)), 
            dtype=torch.float32
        )
        
        # Export to ONNX
        onnx_path = f"btc_predictor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.onnx"
        
        torch.onnx.export(
            model,
            dummy_input,
            onnx_path,
            export_params=True,
            opset_version=11,
            do_constant_folding=True,
            input_names=['features'],
            output_names=['predicted_price'],
            dynamic_axes={
                'features': {0: 'batch_size'},
                'predicted_price': {0: 'batch_size'}
            }
        )
        
        # Optimize ONNX model
        optimized_path = self._optimize_onnx_model(onnx_path)
        
        # Save scaler
        scaler_path = onnx_path.replace('.onnx', '_scaler.pkl')
        joblib.dump(scaler, scaler_path)
        
        logger.info(f"Model exported to ONNX: {optimized_path}")
        return optimized_path, scaler_path
    
    def _optimize_onnx_model(self, onnx_path: str) -> str:
        """Optimize ONNX model for inference performance"""
        
        import onnx
        from onnxoptimizer import optimize
        
        # Load model
        model = onnx.load(onnx_path)
        
        # Apply optimizations
        optimized_model = optimize(model, passes=[
            'eliminate_deadend',
            'eliminate_identity',
            'eliminate_nop_dropout',
            'eliminate_nop_pad',
            'eliminate_unused_initializer',
            'extract_constant_to_initializer',
            'fuse_add_bias_into_conv',
            'fuse_consecutive_squeezes',
            'fuse_consecutive_transposes',
            'fuse_matmul_add_bias_into_gemm',
            'fuse_pad_into_conv',
            'fuse_transpose_into_gemm'
        ])
        
        # Save optimized model
        optimized_path = onnx_path.replace('.onnx', '_optimized.onnx')
        onnx.save(optimized_model, optimized_path)
        
        return optimized_path
```

## Model Validation and Testing

### 1. Performance Validation

#### Prediction Accuracy Metrics
```python
class ModelValidator:
    def __init__(self, config: dict):
        self.config = config
    
    def validate_model(self, model: BitcoinPriceMLP, scaler: StandardScaler, 
                      test_data: pd.DataFrame) -> dict:
        """Comprehensive model validation"""
        
        feature_columns = self._get_feature_columns()
        X_test = test_data[feature_columns].values.astype(np.float32)
        y_test = test_data['target_price'].values
        current_prices = test_data['current_price'].values
        
        # Make predictions
        X_test_scaled = scaler.transform(X_test)
        
        model.eval()
        with torch.no_grad():
            predictions = model(torch.tensor(X_test_scaled)).numpy().flatten()
        
        # Calculate metrics
        mae = np.mean(np.abs(predictions - y_test))
        rmse = np.sqrt(np.mean((predictions - y_test) ** 2))
        mape = np.mean(np.abs((predictions - y_test) / y_test)) * 100
        
        # Directional accuracy
        actual_direction = np.sign(y_test - current_prices)
        predicted_direction = np.sign(predictions - current_prices)
        directional_accuracy = np.mean(actual_direction == predicted_direction)
        
        # Correlation
        correlation = np.corrcoef(predictions, y_test)[0, 1]
        
        # Confidence calibration
        confidence_metrics = self._validate_confidence_calibration(
            predictions, y_test, current_prices
        )
        
        validation_results = {
            'mae': mae,
            'rmse': rmse,
            'mape': mape,
            'directional_accuracy': directional_accuracy,
            'correlation': correlation,
            'prediction_samples': len(predictions),
            **confidence_metrics
        }
        
        # Check if model meets requirements
        validation_results['meets_requirements'] = self._check_requirements(validation_results)
        
        return validation_results
    
    def _validate_confidence_calibration(self, predictions: np.ndarray, 
                                       actual: np.ndarray, current_prices: np.ndarray) -> dict:
        """Validate prediction confidence calibration"""
        
        # Calculate prediction errors
        errors = np.abs(predictions - actual)
        
        # Simple confidence based on price volatility
        price_volatilities = np.abs(actual - current_prices) / current_prices
        confidence_scores = 1.0 - np.clip(price_volatilities * 10, 0, 0.8)
        
        # Calibration metrics
        high_conf_mask = confidence_scores > 0.8
        med_conf_mask = (confidence_scores > 0.5) & (confidence_scores <= 0.8)
        low_conf_mask = confidence_scores <= 0.5
        
        if np.sum(high_conf_mask) > 0:
            high_conf_mae = np.mean(errors[high_conf_mask])
        else:
            high_conf_mae = np.nan
            
        if np.sum(med_conf_mask) > 0:
            med_conf_mae = np.mean(errors[med_conf_mask])
        else:
            med_conf_mae = np.nan
            
        if np.sum(low_conf_mask) > 0:
            low_conf_mae = np.mean(errors[low_conf_mask])
        else:
            low_conf_mae = np.nan
        
        return {
            'high_confidence_mae': high_conf_mae,
            'medium_confidence_mae': med_conf_mae,
            'low_confidence_mae': low_conf_mae,
            'avg_confidence': np.mean(confidence_scores)
        }
    
    def _check_requirements(self, results: dict) -> bool:
        """Check if model meets deployment requirements"""
        
        requirements = [
            results['directional_accuracy'] >= self.config['validation']['min_accuracy_threshold'],
            results['mae'] <= self.config['validation']['max_mae_threshold'],
            results['correlation'] >= self.config['validation']['min_correlation'],
            not np.isnan(results['correlation'])
        ]
        
        return all(requirements)
```

### 2. Inference Performance Testing

#### Latency Validation
```python
class InferencePerformanceTester:
    def __init__(self, onnx_model_path: str, scaler_path: str):
        import onnxruntime as ort
        
        self.session = ort.InferenceSession(onnx_model_path)
        self.scaler = joblib.load(scaler_path)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
    
    def test_inference_latency(self, n_tests: int = 1000) -> dict:
        """Test model inference latency requirements"""
        
        # Generate random test data
        input_size = self.session.get_inputs()[0].shape[1]
        test_data = np.random.random((n_tests, input_size)).astype(np.float32)
        
        # Warm up
        for _ in range(100):
            scaled_input = self.scaler.transform(test_data[:1])
            self.session.run([self.output_name], {self.input_name: scaled_input})
        
        # Measure latency
        latencies = []
        
        for i in range(n_tests):
            start_time = time.perf_counter()
            
            # Scale features
            scaled_input = self.scaler.transform(test_data[i:i+1])
            
            # Model inference
            prediction = self.session.run([self.output_name], {self.input_name: scaled_input})
            
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            latencies.append(latency_ms)
        
        latency_stats = {
            'mean_latency_ms': np.mean(latencies),
            'p50_latency_ms': np.percentile(latencies, 50),
            'p95_latency_ms': np.percentile(latencies, 95),
            'p99_latency_ms': np.percentile(latencies, 99),
            'max_latency_ms': np.max(latencies),
            'std_latency_ms': np.std(latencies)
        }
        
        # Check latency requirements
        target_latency = 30  # 30ms target for inference
        latency_stats['meets_latency_requirement'] = latency_stats['p99_latency_ms'] <= target_latency
        
        return latency_stats
```

## Model Deployment Pipeline

### 1. Model Registry and Versioning

#### S3 Model Registry
```python
class ModelRegistry:
    def __init__(self, s3_bucket: str, registry_prefix: str = "models"):
        self.s3_bucket = s3_bucket
        self.registry_prefix = registry_prefix
        self.s3_client = boto3.client('s3')
    
    def register_model(self, model_path: str, scaler_path: str, 
                      validation_results: dict, metadata: dict) -> str:
        """Register new model version in S3 registry"""
        
        # Generate model version
        model_version = f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Upload model files
        model_key = f"{self.registry_prefix}/btc_predictor/{model_version}/model.onnx"
        scaler_key = f"{self.registry_prefix}/btc_predictor/{model_version}/scaler.pkl"
        
        self.s3_client.upload_file(model_path, self.s3_bucket, model_key)
        self.s3_client.upload_file(scaler_path, self.s3_bucket, scaler_key)
        
        # Create model metadata
        model_metadata = {
            "model_version": model_version,
            "model_path": f"s3://{self.s3_bucket}/{model_key}",
            "scaler_path": f"s3://{self.s3_bucket}/{scaler_key}",
            "created_at": datetime.now().isoformat(),
            "validation_results": validation_results,
            "training_metadata": metadata,
            "deployment_status": "registered"
        }
        
        # Upload metadata
        metadata_key = f"{self.registry_prefix}/btc_predictor/{model_version}/metadata.json"
        self.s3_client.put_object(
            Bucket=self.s3_bucket,
            Key=metadata_key,
            Body=json.dumps(model_metadata, indent=2),
            ContentType='application/json'
        )
        
        logger.info(f"Model {model_version} registered in model registry")
        return model_version
    
    def list_models(self, limit: int = 10) -> List[dict]:
        """List registered models sorted by creation date"""
        
        prefix = f"{self.registry_prefix}/btc_predictor/"
        
        paginator = self.s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=self.s3_bucket, Prefix=prefix)
        
        models = []
        for page in pages:
            for obj in page.get('Contents', []):
                if obj['Key'].endswith('/metadata.json'):
                    metadata = self._load_model_metadata(obj['Key'])
                    models.append(metadata)
        
        # Sort by creation date (newest first)
        models.sort(key=lambda x: x['created_at'], reverse=True)
        
        return models[:limit]
    
    def get_latest_model(self, status_filter: str = "deployed") -> dict:
        """Get latest model with specified status"""
        
        models = self.list_models(limit=50)
        
        for model in models:
            if model.get('deployment_status') == status_filter:
                return model
        
        return None
```

### 2. A/B Testing and Gradual Rollout

#### Model Deployment Controller
```python
class ModelDeploymentController:
    def __init__(self, model_registry: ModelRegistry, config: dict):
        self.model_registry = model_registry
        self.config = config
    
    def deploy_model(self, model_version: str, rollout_percentage: float = 10.0) -> bool:
        """Deploy model with gradual rollout"""
        
        # Validate model exists and meets requirements
        model_metadata = self.model_registry.get_model_metadata(model_version)
        if not model_metadata:
            raise ValueError(f"Model {model_version} not found in registry")
        
        if not model_metadata['validation_results']['meets_requirements']:
            raise ValueError(f"Model {model_version} does not meet deployment requirements")
        
        # Start gradual rollout
        deployment_config = {
            "model_version": model_version,
            "rollout_percentage": rollout_percentage,
            "deployment_start": datetime.now().isoformat(),
            "deployment_status": "rolling_out",
            "previous_model": self._get_current_deployed_model()
        }
        
        # Update deployment configuration
        self._update_deployment_config(deployment_config)
        
        # Update model status in registry
        model_metadata['deployment_status'] = 'rolling_out'
        self.model_registry.update_model_metadata(model_version, model_metadata)
        
        logger.info(f"Started gradual rollout of {model_version} at {rollout_percentage}%")
        return True
    
    def promote_model(self, model_version: str) -> bool:
        """Promote model to full production after successful A/B test"""
        
        # Validate A/B test results
        ab_results = self._get_ab_test_results(model_version)
        
        if not self._validate_ab_results(ab_results):
            logger.warning(f"A/B test results for {model_version} do not meet promotion criteria")
            return False
        
        # Promote to 100% traffic
        deployment_config = {
            "model_version": model_version,
            "rollout_percentage": 100.0,
            "deployment_status": "deployed",
            "promotion_time": datetime.now().isoformat(),
            "ab_test_results": ab_results
        }
        
        self._update_deployment_config(deployment_config)
        
        # Update model status
        model_metadata = self.model_registry.get_model_metadata(model_version)
        model_metadata['deployment_status'] = 'deployed'
        self.model_registry.update_model_metadata(model_version, model_metadata)
        
        logger.info(f"Model {model_version} promoted to full production")
        return True
    
    def rollback_model(self, reason: str) -> bool:
        """Rollback to previous model version"""
        
        current_deployment = self._get_current_deployment_config()
        previous_model = current_deployment.get('previous_model')
        
        if not previous_model:
            logger.error("No previous model available for rollback")
            return False
        
        # Rollback deployment
        rollback_config = {
            "model_version": previous_model,
            "rollout_percentage": 100.0,
            "deployment_status": "deployed",
            "rollback_time": datetime.now().isoformat(),
            "rollback_reason": reason
        }
        
        self._update_deployment_config(rollback_config)
        
        logger.info(f"Rolled back to model {previous_model}. Reason: {reason}")
        return True
```

## Performance Monitoring

### Training Metrics
- `trainer_training_duration_seconds` - Model training time
- `trainer_validation_accuracy` - Model validation accuracy
- `trainer_model_size_mb` - Model file size
- `trainer_inference_latency_ms` - ONNX inference latency
- `trainer_data_samples_processed` - Training data volume

### Model Quality Metrics
- `model_directional_accuracy` - Prediction direction accuracy
- `model_mae` - Mean absolute error
- `model_correlation` - Prediction correlation with actual
- `model_confidence_calibration` - Confidence score calibration

### Performance Targets
```
Component                        Target
──────────────────────────────────────────
Training Duration               < 2 hours
Directional Accuracy            > 55%
Mean Absolute Error             < $50
Prediction Correlation          > 0.3
Inference Latency (P99)         < 30ms
Model Size                      < 50MB
```

This training service ensures continuous model improvement for 10-second Bitcoin price predictions through automated S3 gold layer processing, inference-optimized model development, and systematic deployment with A/B testing capabilities.