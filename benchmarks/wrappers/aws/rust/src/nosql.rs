use aws_sdk_dynamodb::{Client, types::AttributeValue};
use std::collections::HashMap;
use std::env;

pub struct NoSQL {
    client: Client,
    tables: std::sync::Mutex<HashMap<String, String>>,
}

impl NoSQL {
    pub async fn get_instance() -> Self {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let client = Client::new(&config);
        NoSQL {
            client,
            tables: std::sync::Mutex::new(HashMap::new()),
        }
    }

    fn get_table_name(&self, table_name: &str) -> Result<String, String> {
        let mut tables = self.tables.lock().unwrap();
        if let Some(name) = tables.get(table_name) {
            return Ok(name.clone());
        }

        let env_name = format!("NOSQL_STORAGE_TABLE_{}", table_name);
        match env::var(&env_name) {
            Ok(aws_name) => {
                tables.insert(table_name.to_string(), aws_name.clone());
                Ok(aws_name)
            }
            Err(_) => Err(format!("Couldn't find environment variable {} for table {}", env_name, table_name)),
        }
    }

    // Helper to convert HashMap<String, AttributeValue> to generic JSON/Map
    // For simplicity in this wrapper, we accept/return HashMap<String, AttributeValue> 
    // or we could use serde_dynamo if added as dependency. 
    // Following the python "dict" approach, we'll try to use AttributeValue directly or simple conversion.
    // For now, let's expose the raw AttributeValue or simple helpers.
    
    pub async fn insert(
        &self,
        table_name: &str,
        primary_key: (&str, &str),
        secondary_key: (&str, &str),
        mut data: HashMap<String, AttributeValue>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let aws_table_name = self.get_table_name(table_name)?;
        
        data.insert(primary_key.0.to_string(), AttributeValue::S(primary_key.1.to_string()));
        data.insert(secondary_key.0.to_string(), AttributeValue::S(secondary_key.1.to_string()));

        self.client
            .put_item()
            .table_name(aws_table_name)
            .set_item(Some(data))
            .send()
            .await?;

        Ok(())
    }

    pub async fn get(
        &self,
        table_name: &str,
        primary_key: (&str, &str),
        secondary_key: (&str, &str),
    ) -> Result<HashMap<String, AttributeValue>, Box<dyn std::error::Error>> {
        let aws_table_name = self.get_table_name(table_name)?;
        
        let mut key = HashMap::new();
        key.insert(primary_key.0.to_string(), AttributeValue::S(primary_key.1.to_string()));
        key.insert(secondary_key.0.to_string(), AttributeValue::S(secondary_key.1.to_string()));

        let resp = self.client
            .get_item()
            .table_name(aws_table_name)
            .set_key(Some(key))
            .send()
            .await?;

        Ok(resp.item.unwrap_or_default())
    }
    
    // Minimal implementation matching the python basics. 
    // update/query/delete can be added similarly.
}
