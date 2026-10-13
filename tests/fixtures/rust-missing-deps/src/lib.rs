/// Formats a number with the itoa crate.
pub fn show(n: i32) -> String {
    itoa::Buffer::new().format(n).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shows() {
        assert_eq!(show(5), "5");
    }
}
