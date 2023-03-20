import click
import datetime

class Colors:
    SUCCESS = "\033[92m"
    STATUS = "\033[94m"
    WARNING = "\033[93m"
    ERROR = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"

class ColoredPrinter:
    @staticmethod
    def print(color, logging_instance, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        logging_instance.info(message)
        click.echo(f"{color}{Colors.BOLD}[{timestamp}]{Colors.END} {message}")