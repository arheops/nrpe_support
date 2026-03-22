#!/usr/bin/python3

import os
import re
import sys
from enum import Enum
from subprocess import PIPE, CalledProcessError, Popen

import argparse


class NagiosResponseCode(Enum):
    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = 3


class AstChannelsCheck:
    SUDO_CMD = """/usr/bin/sudo"""
    CHANNELS_CMD = """/usr/sbin/asterisk -rx "core show channels count" """
    PEERS_CMD = """/usr/sbin/asterisk -rx "sip show peers" """
    CHANNELS_SAMPLE_OUTPUT = """
    52 active channels
    26 active calls
    3069 calls processed
    """
    PEERS_SAMPLE_OUTPUT = """
    313 sip peers [Monitored: 3 online, 310 offline Unmonitored: 0 online, 0 offline]
    """

    def __init__(self):
        self.return_code = NagiosResponseCode.UNKNOWN.value
        self.return_msg = NagiosResponseCode.UNKNOWN.name
        self.count = 0
        self.critical_peers = []
        self.args = None
        self.warn_threshold = 100
        self.critical_threshold = 1000

    @staticmethod
    def get_parser():
        parser = argparse.ArgumentParser()
        parser.add_argument("-w", help="warning threshold")
        parser.add_argument("-c", help="critical threshold")
        parser.add_argument("-C", help="Command: install, channels, peers")
        parser.add_argument(
            "--critical-peers",
            help="List of peers which are critical and should be online, comma separated",
        )
        return parser

    def get_args(self):
        parser = self.get_parser()
        self.args = parser.parse_args()

        if self.args.C is None:
            print("Use with -h for help")
            sys.exit(3)

        if self.args.w is not None:
            self.warn_threshold = int(self.args.w)

        if self.args.c is not None:
            self.critical_threshold = int(self.args.c)

        if self.args.critical_peers is not None:
            self.critical_peers = self.args.critical_peers.split(",")

    def get_command(self):
        if self.args.C is None:
            return ""
        return self.args.C

    @staticmethod
    def clean_output(output):
        return [
            line for line in output.splitlines()
            if not line.startswith("Asterisk ending")
        ]

    @staticmethod
    def make_install():
        myself = sys.argv[0]
        os.system(
            f"""echo 'nagios    ALL= NOPASSWD: {myself}'>>/etc/sudoers.d/nagios_asterisk"""
        )

    def get_channels(self):
        self.count = 0
        return_string = ""
        try:
            with Popen(
                self.SUDO_CMD + " " + self.CHANNELS_CMD,
                stdout=PIPE,
                stderr=None,
                shell=True,
            ) as process:
                output = self.clean_output(
                    process.communicate()[0].decode("utf-8")
                )
                channels, calls, processed_calls = re.findall(
                    r"\d+", " ".join(output)
                )
                self.count = int(calls)
                return_string = (
                    "{} active channels "
                    "{} active calls "
                    "{} calls processed"
                ).format(channels, calls, processed_calls)
                performance = (
                    "'channels.active'={};"
                    "{};{};;"
                    " 'calls.active'={};;;;"
                ).format(channels, self.warn_threshold, self.critical_threshold, calls)
                return_string += " | " + performance
                self.return_code = NagiosResponseCode.OK
        except CalledProcessError as e:
            print("ERROR: Error running command (line {}): {}".format(
                e.__traceback__.tb_lineno, e))
            self.return_code = NagiosResponseCode.UNKNOWN
        except Exception as e:
            print("ERROR: Error in code (line {}): {}".format(
                e.__traceback__.tb_lineno, e))
            self.return_code = NagiosResponseCode.UNKNOWN

        self.process_output(return_string)

    def get_peers(self):
        self.count = 0
        return_string = ""
        try:
            with Popen(
                self.SUDO_CMD + " " + self.PEERS_CMD,
                stdout=PIPE,
                stderr=None,
                shell=True,
            ) as process:
                output = self.clean_output(
                    process.communicate()[0].decode("utf-8")
                )
                peers_critical_online, peers_critical_offline = (
                    self.check_critical_peers(output)
                )

                last_line = output[-1]
                result_array = [int(val) for val in re.findall(r"\d+", last_line)]
                (
                    peers,
                    monitored_online,
                    monitored_offline,
                    unmonitored_online,
                    unmonitored_offline,
                ) = result_array

                self.count = peers
                online_all = monitored_online + unmonitored_online
                offline_all = monitored_offline + unmonitored_offline
                return_string = (
                    "{} sip peers, {} online, {} offline"
                ).format(peers, online_all, offline_all)

                performance = (
                    "'peers.all'={};"
                    "{};{};;"
                    " 'peers.monitored.online'={};;;;"
                    " 'peers.monitored.offline'={};;;;"
                    " 'peers.unmonitored.online'={};;;;"
                    " 'peers.unmonitored.offline'={};;;;"
                    " 'peers.critical.online'={};;;;"
                    " 'peers.critical.offline'={};;;;"
                ).format(
                    peers, self.warn_threshold, self.critical_threshold,
                    monitored_online, monitored_offline,
                    unmonitored_online, unmonitored_offline,
                    peers_critical_online, peers_critical_offline,
                )
                return_string += " | " + performance
                self.return_code = NagiosResponseCode.OK
        except CalledProcessError as e:
            print("ERROR: Error running command (line {}): {}".format(
                e.__traceback__.tb_lineno, e))
            self.return_code = NagiosResponseCode.UNKNOWN
        except Exception as e:
            print("ERROR: Error in code (line {}): {}".format(
                e.__traceback__.tb_lineno, e))
            self.return_code = NagiosResponseCode.UNKNOWN

        self.process_output(return_string)

    @staticmethod
    def check_critical_peers(output):
        return [0, 0]

    def process_output(self, return_string):
        if self.return_code == NagiosResponseCode.UNKNOWN:
            sys.exit(NagiosResponseCode.UNKNOWN.value)

        if self.count >= self.critical_threshold:
            self.return_code = NagiosResponseCode.CRITICAL.value
            self.return_msg = NagiosResponseCode.CRITICAL.name
        elif self.count >= self.warn_threshold:
            self.return_code = NagiosResponseCode.WARNING.value
            self.return_msg = NagiosResponseCode.WARNING.name
        else:
            self.return_code = NagiosResponseCode.OK.value
            self.return_msg = NagiosResponseCode.OK.name

        print("{}: {}".format(self.return_msg, return_string))
        sys.exit(self.return_code)

    def process(self):
        self.get_args()
        command = self.get_command()

        if command == "install":
            self.make_install()
        elif command == "channels":
            self.get_channels()
        elif command == "peers":
            self.get_peers()


if __name__ == "__main__":
    checker = AstChannelsCheck()
    checker.process()