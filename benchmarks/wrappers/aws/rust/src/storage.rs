use aws_sdk_s3::Client;
use aws_sdk_s3::primitives::ByteStream;
use std::path::Path;
use uuid::Uuid;
use std::fs;
use std::io::Write;

pub struct Storage {
    client: Client,
}

impl Storage {
    pub async fn get_instance() -> Self {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let client = Client::new(&config);
        Storage { client }
    }

    fn unique_name(name: &str) -> String {
        let path = Path::new(name);
        let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or(name);
        let ext = path.extension().and_then(|s| s.to_str()).map(|e| format!(".{}", e)).unwrap_or_default();
        let uuid = Uuid::new_v4().to_string();
        let uuid_short = uuid.split('-').next().unwrap_or(&uuid);
        format!("{}.{}{}", stem, uuid_short, ext)
    }

    pub async fn upload(&self, bucket: &str, file: &str, filepath: &str) -> Result<String, Box<dyn std::error::Error>> {
        let key_name = Self::unique_name(file);
        let body = ByteStream::from_path(Path::new(filepath)).await?;
        
        self.client
            .put_object()
            .bucket(bucket)
            .key(&key_name)
            .body(body)
            .send()
            .await?;
            
        Ok(key_name)
    }

    pub async fn download(&self, bucket: &str, file: &str, filepath: &str) -> Result<(), Box<dyn std::error::Error>> {
        let resp = self.client
            .get_object()
            .bucket(bucket)
            .key(file)
            .send()
            .await?;
            
        let data = resp.body.collect().await?;
        let mut file = fs::File::create(filepath)?;
        file.write_all(&data.into_bytes())?;
        
        Ok(())
    }

    pub async fn upload_stream(&self, bucket: &str, file: &str, data: Vec<u8>) -> Result<String, Box<dyn std::error::Error>> {
        let key_name = Self::unique_name(file);
        let body = ByteStream::from(data);
        
        self.client
            .put_object()
            .bucket(bucket)
            .key(&key_name)
            .body(body)
            .send()
            .await?;
            
        Ok(key_name)
    }

    pub async fn download_stream(&self, bucket: &str, file: &str) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
        let resp = self.client
            .get_object()
            .bucket(bucket)
            .key(file)
            .send()
            .await?;
            
        let data = resp.body.collect().await?;
        Ok(data.into_bytes().to_vec())
    }
}
