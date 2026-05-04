"""CLI entry point for sample_app."""

from sample_app.utils import format_message


def main() -> None:
    print(format_message("hello", "world"))


if __name__ == "__main__":
    main()
