use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
pub struct RequestPayload {
    pub username: String,
    pub random_len: usize,
}

#[derive(Serialize)]
pub struct FunctionResponse {
    pub result: String,
}

pub fn handler(event: RequestPayload) -> FunctionResponse {
    // Generate random numbers
    use rand::Rng;
    let mut rng = rand::thread_rng();
    let random_numbers: Vec<u32> = (0..event.random_len)
        .map(|_| rng.gen_range(0..1_000_000))
        .collect();

    // Get current time formatted as locale string
    use chrono::Local;
    let cur_time = Local::now().format("%Y-%m-%d %H:%M:%S").to_string();

    // Use embedded template (compiled into binary)
    // This is more reliable than reading from filesystem in Lambda
    let template_content = include_str!("templates/template.html");

    // Simple template rendering (replace placeholders)
    // Generate list items for random numbers
    let list_items: String = random_numbers
        .iter()
        .map(|n| format!("        <li>{}</li>", n))
        .collect::<Vec<_>>()
        .join("\n");
    
    // Replace template variables
    let html = template_content
        .replace("{{username}}", &event.username)
        .replace("{{cur_time}}", &cur_time)
        // Replace the entire loop block with generated list items
        .replace(
            "        {% for n in random_numbers %}\n        <li>{{n}}</li>\n        {% endfor %}",
            &list_items,
        );

    FunctionResponse {
        result: html,
    }
}

