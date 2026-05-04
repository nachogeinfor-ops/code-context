// Sample Rust file for tree-sitter chunker tests.

pub struct User {
    pub id: u32,
    pub name: String,
}

pub enum Greeting {
    Casual,
    Formal,
}

pub fn format_message(name: &str) -> String {
    format!("hello, {}!", name)
}

impl User {
    pub fn display(&self) -> String {
        format!("{}: {}", self.id, self.name)
    }
}
