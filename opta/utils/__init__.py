import logging
import os
import sys
from logging import Formatter, Logger, LogRecord
from logging.handlers import QueueHandler, QueueListener
from queue import Queue
from shutil import which
from textwrap import dedent
from time import sleep
from typing import Any, Dict, Generator, List, Optional, Tuple

import click
from ruamel.yaml import YAML

from opta.constants import DEV_VERSION, VERSION
from opta.datadog_logging import DatadogLogHandler
from opta.exceptions import UserErrors
from opta.special_formatter import PartialFormatter

yaml = YAML(typ="safe")


class LogFormatMultiplexer(Formatter):
    def __init__(
        self,
        debug_formatter: Optional[Formatter] = None,
        info_formatter: Optional[Formatter] = None,
        warning_formatter: Optional[Formatter] = None,
        error_formatter: Optional[Formatter] = None,
        critical_formatter: Optional[Formatter] = None,
        default_formatter: Optional[Formatter] = None,
    ):
        self.default_formatter = default_formatter or Formatter(
            "%(levelname)s: %(message)s"
        )
        self.formatter_mapping = {
            "DEBUG": debug_formatter or self.default_formatter,
            "INFO": info_formatter or self.default_formatter,
            "WARNING": warning_formatter or self.default_formatter,
            "ERROR": error_formatter or self.default_formatter,
            "CRITICAL": critical_formatter or self.default_formatter,
        }

    def format(self, record: LogRecord) -> str:
        return self.formatter_mapping.get(
            record.levelname, self.default_formatter
        ).format(record)


def initialize_logger() -> Tuple[Logger, QueueListener, DatadogLogHandler]:
    logger = logging.getLogger("opta")
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler(sys.stdout)
    if os.environ.get("OPTA_DEBUG") is None:
        ch.setLevel(logging.INFO)
        formatter = LogFormatMultiplexer(info_formatter=Formatter("%(message)s"))
    else:
        ch.setLevel(logging.DEBUG)
        formatter = LogFormatMultiplexer()
    dd_queue: Queue = Queue(-1)
    queue_handler = QueueHandler(dd_queue)
    queue_handler.setLevel(logging.DEBUG)
    dd_handler = DatadogLogHandler()
    dd_handler.setLevel(logging.DEBUG)
    dd_listener = QueueListener(dd_queue, dd_handler)
    ch.setFormatter(formatter)
    logger.addHandler(queue_handler)
    logger.addHandler(ch)
    logger.propagate = False
    dd_listener.start()
    return logger, dd_listener, dd_handler


logger, dd_listener, dd_handler = initialize_logger()
# Don't send logs to datadog during tests
if hasattr(sys, "_called_from_test") or VERSION == DEV_VERSION:
    dd_handler.setLevel(logging.CRITICAL)

fmt = PartialFormatter("")


class RawString(str):
    """This class can be used to avoid formatting the string in the hydrate method"""

    # TODO: This should not actually exist. It is purely a workaround
    pass


def deep_merge(dict1: Dict[Any, Any], dict2: Dict[Any, Any]) -> Dict[Any, Any]:
    dict2 = dict2.copy()
    for key, value in dict1.items():
        if key in dict2:
            if isinstance(value, dict) and isinstance(dict2[key], dict):
                dict2[key] = deep_merge(value, dict2[key])
            elif value != dict2[key]:
                raise Exception(f"Cant merge conflicting non-dict values (key: {key})")
        else:
            dict2[key] = value

    return dict2


def hydrate(target: Any, hydration: Dict[Any, Any]) -> Dict[Any, Any]:
    if isinstance(target, dict):
        target = target.copy()
        for k, v in target.items():
            target[k] = hydrate(v, hydration)
    elif isinstance(target, list):
        target = [hydrate(x, hydration) for x in target]
    elif isinstance(target, RawString):  # TODO: No, just no
        target = str(target)  # https://www.youtube.com/watch?v=31g0YE61PLQ
    elif isinstance(target, str):
        target = fmt.format(target, **hydration)

    return target


def is_tool(name: str) -> bool:
    """Check whether `name` is on PATH and marked as executable."""
    return which(name) is not None


def safe_run(func):  # type: ignore
    def func_wrapper(*args, **kwargs):  # type: ignore
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if hasattr(sys, "_called_from_test"):
                raise e
            else:
                print(e)
                return None

    return func_wrapper


def fmt_msg(message: str) -> str:
    """Format triple quote python strings"""
    # TODO: Replace with better message formatting
    message = dedent(message)
    message = message.replace("\n", " ")
    message = message.replace("~", "\n")
    return message


# TODO: Support max-width.
# The data should be a 2D array of the shape rows x columns.
def column_print(data: List[Any]) -> None:
    # Determine the width of each column (the length of the longest word + 1)
    longest_char_len_by_column = [0] * len(data[0])
    for row in data:
        for column_idx, word in enumerate(row):
            longest_char_len_by_column[column_idx] = max(
                len(word), longest_char_len_by_column[column_idx]
            )

    # Create each line of output one at a time.
    lines = []
    for row in data:
        line = []
        for column_idx, word in enumerate(row):
            line.append(word.ljust(longest_char_len_by_column[column_idx]))
        line_out = " ".join(line)
        lines.append(line_out)

    print("\n".join(lines))


# Get all substrings separated by the delimiter.
# Ex: "foo.bar.baz", delimiter = "."
# -> ['foo', 'foo.bar', 'foo.bar.baz', 'bar.baz', 'bar', 'bar.baz', 'baz']
def all_substrings(string: str, delimiter: str = "") -> List[str]:
    all_substrings = []
    words = string.split(delimiter) if len(delimiter) else list(string)

    def add_words(i: int, j: int) -> None:
        if j > len(words):
            return
        substring = delimiter.join(words[i:j])
        all_substrings.append(substring)
        add_words(i, j + 1)
        add_words(i + 1, j + 1)

    add_words(0, 1)
    return all_substrings


# Exponential backoff for some external requests that may not work 100% on the
# first try.
def exp_backoff(num_tries: int = 3) -> Generator:
    seconds = 2

    for _ in range(num_tries):
        yield
        sleep(seconds)
        seconds *= seconds


def check_opta_file_exists(config_path: str) -> str:
    if not os.path.exists(config_path):
        logger.info(
            fmt_msg(
                f"""
            Could not find file: {config_path}. Please provide the path to a valid opta config file.
            When using absolute paths, please do not use `~`.
        """
            )
        )
        prompt_config_path = click.prompt(
            "Enter a Configuration Path (Empty String will exit)",
            default="",
            type=click.STRING,
            show_default=False,
        )

        if not prompt_config_path:
            logger.info("Exiting...")
            sys.exit(0)
        elif not os.path.exists(prompt_config_path):
            raise UserErrors("Invalid Configuration Path provided.")

        config_path = prompt_config_path

    return config_path