#!/usr/bin/env python3

from pathlib import Path
from configparser import ConfigParser
from argparse import ArgumentParser
from re import findall, IGNORECASE
from datetime import timedelta, datetime
from math import floor
from langdetect import detect


class SubBlock:
    index: int
    content: str
    start_time: timedelta
    stop_time: timedelta
    regex_matches: int
    keep: bool

    def __init__(self, index):
        self.index = index
        self.keep = True
        self.regex_matches = 0
        self.content = ""
        self.stop_time = timedelta()
        self.start_time = timedelta()

    def __repr__(self) -> str:

        string = (convert_from_timedelta(self.start_time) +
                  " --> " +
                  convert_from_timedelta(self.stop_time) +
                  "\n")
        string += (self.content + "\n")
        return string


def main():
    home_dir = Path(__file__).absolute().parent
    config_file = home_dir.joinpath("settings.config")
    if not config_file.is_file():
        config_file.write_text(home_dir.joinpath("example-settings.config").read_text())

    args = get_args()
    config = get_config(config_file)

    if args["silent"]:
        config["log_file"] = None

    if config["log_dir"] and not config["log_dir"].is_absolute():
        config["log_dir"] = home_dir.joinpath(config["log_dir"])

    blocks = parse_sub(args["subtitle"])

    run_regex(blocks, config["regex_list"])
    detect_ads_start(blocks)
    detect_ads_end(blocks)

    try:
        publish_sub(args["subtitle"], blocks, config["log_dir"])
    except KeyboardInterrupt as e:
        publish_sub(args["subtitle"], blocks, config["log_dir"])
        raise e

    if args["language"]:
        report_incorrect_lang(blocks, args["language"], args["subtitle"], home_dir)


def get_args() -> dict:
    parser = ArgumentParser(description="Remove ads from subtitle. Removed blocks are sent to logfile. "
                                        "Can also check so that the language match language-label. "
                                        "Edit the settings.config file to change regex filter and "
                                        "where to store log.")

    parser.add_argument("subtitle", metavar="SUB", type=Path, default=None,
                        help="Path to subtitle to run script against. "
                             "Script currently only compatible with simple .srt files.")

    parser.add_argument("--language", "-l", metavar="LANG", type=str, dest="language", default=None,
                        help="Listed language code of the subtitle. if this argument is set then the script will "
                             "check that the language of the content matches LANG. If they don't match an empty "
                             "file called \"[SUB].lang-warn\" will be created alongside the subtitle file. "
                             "Language code according to 2-letter ISO-639, "
                             "[LANG] may contain :forced or other \":<tag>\"")

    parser.add_argument("--silent", "-s", action="store_true", dest="silent",
                        help="Silent: If flag is set then nothing is printed and nothing is logged.")

    args = parser.parse_args()
    subtitle: Path = args.subtitle
    language: str = args.language
    silent: bool = args.silent

    ret = dict()

    # check usage:

    if subtitle is None:
        parser.print_help()
        exit()

    if not subtitle.is_absolute():
        subtitle = Path.cwd().joinpath(subtitle)

    if not subtitle.is_file() or subtitle.name[-4:] != ".srt":
        print("make sure that the subtitle-file is a srt-file")
        print("--help for more information.")
        exit()
    ret["subtitle"] = subtitle

    if language is not None:
        if len(language.split(":")[0]) != 2:
            print("Use 2-letter ISO-639 standard language code.")
            print("--help for more information.")
            exit()
        ret["language"] = language.split(":")[0].lower()
    else:
        ret["language"] = None

    ret["silent"] = silent

    return ret


def get_config(config_file: Path) -> dict:
    cfg = ConfigParser()
    cfg.read(str(config_file))
    regex_list = list()
    for regex in list(cfg.items("REGEX")):
        if len(regex[1]) != 0:
            regex_list.append(regex[1])
    try:
        log_dir = Path(cfg.get("SETTINGS", "log_dir"))
    except KeyError:
        log_dir = None
    if not log_dir or log_dir.is_dir():
        log_dir = None

    return {"regex_list": regex_list, "log_dir": log_dir}


def parse_sub(subtitle: Path) -> list:
    with subtitle.open(mode="r") as file:
        lines = file.readlines()
        lines = [line.rstrip() for line in lines]
    lines.append("")

    current_index = 1
    block = SubBlock(1)
    blocks = list()
    for line in lines:
        if len(line) == 0:
            if len(block.content) > 0:
                blocks.append(block)
                current_index += 1
                block = SubBlock(current_index)
            continue

        if " --> " in line and block.stop_time.seconds == 0:
            start_string = line.split(" --> ")[0].rstrip()[:12]
            block.start_time = convert_to_timedelta(start_string)

            stop_string = line.split(" --> ")[1].rstrip()[:12]
            block.stop_time = convert_to_timedelta(stop_string)
            continue

        if block.stop_time.seconds == 0:
            continue

        block.content = block.content + line + "\n"

    return blocks


def convert_to_timedelta(timing: str) -> timedelta:
    timing = timing.replace(".", ",")
    split = timing.split(":")

    return timedelta(hours=float(split[0]),
                     minutes=float(split[1]),
                     seconds=float(split[2].split(",")[0]),
                     milliseconds=float(split[2].split(",")[1]))


def convert_from_timedelta(timing: timedelta) -> str:
    time = timing.total_seconds()

    hours = floor(time / (60*60))
    time = time - hours * (60*60)

    minutes = floor(time / 60)
    time = time - minutes * 60

    seconds = floor(time)
    time = time - seconds

    mill = floor(time*1000)

    hours_str = str(hours)
    minutes_str = str(minutes)
    seconds_str = str(seconds)
    mill_str = str(mill)

    hours_str = "0" * (2 - len(hours_str)) + hours_str
    minutes_str = "0" * (2 - len(minutes_str)) + minutes_str
    seconds_str = "0" * (2 - len(seconds_str)) + seconds_str
    mill_str = mill_str + "0" * (3 - len(mill_str))

    return hours_str + ":" + minutes_str + ":" + seconds_str + "," + mill_str


def publish_sub(subtitle: Path, blocks: list, log: Path):
    i = 1
    sub_file_content = ""
    log_entry = ""
    for block in blocks:
        block: SubBlock

        if not block.keep:
            if log:
                log_entry += (str(block.index) + "\n")
                log_entry += (str(block))
            continue

        sub_file_content += (str(i) + "\n")
        sub_file_content += (str(block))
        i += 1

    if len(sub_file_content) == 0:
        print("After processing the subtitle nothing was left in the file. No changes will be made, exiting.")
        exit()
    with subtitle.open(mode="w") as sub_file:
        sub_file.write(sub_file_content[:-1])

    if len(log_entry) > 0:
        print("Blocks removed from subtitle:\n" + log_entry)
        log_entry = "[ --- Blocks removed from \"" + subtitle.name + "\" ---]:\n" + log_entry
        log_entry += "[-----------------------------------------------------------------------------------------------]"
        log_entry = "\n".join(str(datetime.now())[:19] + ": " + line for line in log_entry.split("\n")) + "\n"

        try:
            log.parent.mkdir()
        except FileExistsError:
            pass
        remove_log = log.joinpath("removed.log")
        with remove_log.open(mode="a") as log_file:
            log_file.write(log_entry)


def check_lang(blocks: list, language: str) -> bool:
    content = ""
    for block in blocks:
        if block.keep:
            content = content + block.content
    return detect(content) == language


def run_regex(blocks, regex_list):
    for block in blocks:
        for regex in regex_list:
            result = findall(regex, block.content.replace("\n", " "), flags=IGNORECASE)
            if result is not None:
                block.regex_matches += len(result)


def detect_ads_start(blocks: list):
    max_index = len(blocks)
    for block in blocks:
        block: SubBlock
        if block.start_time.seconds < 900:
            max_index = block.index

    best_match_index = None
    highest_score = 0
    for block in blocks[:max_index]:
        if block.regex_matches > highest_score:
            best_match_index = block.index
            highest_score = block.regex_matches

    if best_match_index is None:
        return

    for block in blocks[max(0, best_match_index - 2): min(len(blocks), best_match_index + 2)]:
        if block.regex_matches > 0:
            block.keep = False


def detect_ads_end(blocks: list):
    min_index = max(0, len(blocks) - 10)

    best_match_index = None
    highest_score = 0
    for block in blocks[min_index:]:
        if block.regex_matches > highest_score:
            best_match_index = block.index
            highest_score = block.regex_matches

    if best_match_index is None:
        return

    for block in blocks[max(0, best_match_index - 2): min(len(blocks), best_match_index + 2)]:
        if block.regex_matches > 0:
            block.keep = False


def report_incorrect_lang(blocks: list, language: str, subtitle: Path, home_dir: Path):
    warn_path = Path(home_dir, subtitle.name + ".lang-warn")

    if not check_lang(blocks, language):
        with warn_path.open(mode='w') as file:
            file.write(str(subtitle) + " is not the correct language, Please verify.")
    else:
        try:
            warn_path.unlink()
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted")
        exit()
    except UnicodeDecodeError:
        print("Unable to read file, Unicode decode error")
        exit()
