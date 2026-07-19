import os
import shlex
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "tmux-theme-sync.sh"


class TmuxThemeSyncInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.home = self.root / "home"
        self.fake_bin = self.root / "bin"
        self.home.mkdir()
        self.fake_bin.mkdir()
        self.tmux_log = self.root / "tmux.log"
        self._write_executable(
            self.fake_bin / "tmux",
            """#!/usr/bin/env bash
printf '%s\n' "$*" >> "${TMUX_TEST_LOG:?}"
if [[ "${1:-}" == "has-session" ]]; then
  exit 1
fi
if [[ "${1:-}" == "list-panes" && -n "${TMUX_TEST_TTY:-}" ]]; then
  printf '%s\n' "$TMUX_TEST_TTY"
fi
if [[ "${1:-}" == "list-clients" && -n "${TMUX_TEST_TTY:-}" ]]; then
  printf '%s\n' "$TMUX_TEST_TTY"
fi
exit 0
""",
        )
        (self.home / ".zshrc").write_text(
            'alias tlist="tmux-theme"\nalias keep-me="true"\n',
            encoding="utf-8",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _environment(self, **overrides: str) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.fake_bin}:{env['PATH']}",
                "TMUX_TEST_LOG": str(self.tmux_log),
                "TMUX_THEME_SYNC_ENABLED": "false",
                "TMUX_THEME_SYNC_TOKEN": "",
                "TMUX_THEME_SYNC_INTERVAL": "1",
            }
        )
        env.update(overrides)
        for key in ("CODEX_TMUX_THEME_FILE", "CODEX_CONFIG_FILE", "TMUX_THEME_ENV_FILE"):
            if key not in overrides:
                env.pop(key, None)
        return env

    def _install(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(INSTALLER)],
            check=True,
            capture_output=True,
            text=True,
            env=self._environment(**overrides),
        )

    @staticmethod
    def _parse_env_file(path: Path) -> dict[str, str]:
        values = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            parsed = shlex.split(raw_value)
            values[key] = parsed[0] if parsed else ""
        return values

    def test_startup_repairs_missing_or_invalid_state_to_dark(self):
        self._install()

        state_file = self.home / ".codex" / "tmux-theme"
        config_file = self.home / ".codex" / "config.toml"
        self.assertEqual(state_file.read_text(encoding="utf-8"), "dark\n")
        self.assertIn('theme = "base16-ocean-dark"', config_file.read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(state_file.stat().st_mode), 0o600)
        self.assertEqual(list(state_file.parent.glob("tmux-theme.tmp.*")), [])
        tmux_calls = self.tmux_log.read_text(encoding="utf-8")
        self.assertIn(
            "set-option -g status-style bg=#1e1e1e,fg=#dcddde",
            tmux_calls,
        )

        switcher = self.home / ".local" / "bin" / "tmux-theme"
        subprocess.run(
            [str(switcher), "light"],
            check=True,
            capture_output=True,
            text=True,
            env=self._environment(),
        )
        tmux_calls = self.tmux_log.read_text(encoding="utf-8")
        self.assertIn(
            "set-option -g status-style bg=#e5e7eb,fg=#111827",
            tmux_calls,
        )

        state_file.write_text("invalid\n", encoding="utf-8")
        config_file.write_text('[tui]\ntheme = "base16-ocean-light"\n', encoding="utf-8")
        self._install()

        self.assertEqual(state_file.read_text(encoding="utf-8"), "dark\n")
        self.assertIn('theme = "base16-ocean-dark"', config_file.read_text(encoding="utf-8"))

    def test_blank_template_token_preserves_existing_nonempty_token(self):
        env_file = self.home / ".config" / "tmux-theme-sync" / "env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text(
            "TMUX_THEME_SYNC_URL=https://theme.example.test\n"
            "TMUX_THEME_SYNC_ENABLED=false\n"
            "TMUX_THEME_SYNC_TOKEN='kept token'\n"
            "TMUX_THEME_SYNC_INTERVAL=9\n",
            encoding="utf-8",
        )

        self._install(TMUX_THEME_SYNC_TOKEN="")

        values = self._parse_env_file(env_file)
        self.assertEqual(values["TMUX_THEME_SYNC_TOKEN"], "kept token")
        self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)

    def test_poller_repairs_codex_config_when_remote_mode_matches_state(self):
        self._install()
        config_file = self.home / ".codex" / "config.toml"
        config_file.write_text('[tui]\ntheme = "base16-ocean-light"\n', encoding="utf-8")
        env_file = self.home / ".config" / "tmux-theme-sync" / "env"
        env_file.write_text(
            "TMUX_THEME_SYNC_URL=https://theme.example.test\n"
            "TMUX_THEME_SYNC_TOKEN=test-token\n"
            "TMUX_THEME_SYNC_INTERVAL=1\n",
            encoding="utf-8",
        )
        self._write_executable(
            self.fake_bin / "curl",
            "#!/usr/bin/env bash\nprintf '%s\\n' '{\"mode\":\"dark\"}'\n",
        )
        self._write_executable(self.fake_bin / "sleep", "#!/usr/bin/env bash\nexit 42\n")

        poller = self.home / ".local" / "bin" / "tmux-theme-sync-poll"
        result = subprocess.run(
            [str(poller)],
            check=False,
            capture_output=True,
            text=True,
            env=self._environment(TMUX_THEME_SYNC_ENABLED="true"),
        )

        self.assertEqual(result.returncode, 42)
        self.assertIn("applied dark", result.stdout)
        self.assertIn('theme = "base16-ocean-dark"', config_file.read_text(encoding="utf-8"))

    def test_switcher_applies_osc4_fallbacks_directly_and_through_tmux(self):
        tty_file = self.root / "theme.tty"
        tty_file.write_bytes(b"")
        env = self._environment(TMUX_TEST_TTY=str(tty_file))
        self._install(TMUX_TEST_TTY=str(tty_file))
        switcher = self.home / ".local" / "bin" / "tmux-theme"

        expected = {
            "light": {237: "#ffffff", 255: "#ffffff"},
            "dark": {237: "#3a3a3a", 255: "#eeeeee"},
        }
        for mode, palette in expected.items():
            subprocess.run(
                [str(switcher), mode],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            output = tty_file.read_bytes()
            for index, color in palette.items():
                direct = f"\x1b]4;{index};{color}\x07".encode()
                passthrough = (
                    f"\x1bPtmux;\x1b\x1b]4;{index};{color}\x07\x1b\\".encode()
                )
                self.assertEqual(output.count(direct), 2)
                self.assertEqual(output.count(passthrough), 1)

    def test_sync_session_is_system_scoped_and_tlist_alias_is_removed(self):
        self._install()
        zshrc = (self.home / ".zshrc").read_text(encoding="utf-8")
        self.assertNotIn('alias tlist="tmux-theme"', zshrc)
        self.assertIn('alias keep-me="true"', zshrc)

        (self.home / ".config" / "tmux-theme-sync" / "disabled").unlink()
        starter = self.home / ".local" / "bin" / "tmux-theme-sync-start"
        subprocess.run(
            [str(starter)],
            check=True,
            capture_output=True,
            text=True,
            env=self._environment(),
        )
        tmux_calls = self.tmux_log.read_text(encoding="utf-8")
        self.assertIn(
            "set-option -t tmux-theme-sync @nomarh_scope system",
            tmux_calls,
        )

    def test_shell_templates_do_not_define_tlist_as_a_theme_alias(self):
        for path in (INSTALLER, REPO_ROOT / "scripts" / "tools-shell.sh"):
            alias_lines = [
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("alias tlist=")
            ]
            self.assertEqual(alias_lines, [], path)

    def test_startup_guard_repairs_state_and_wrapper_without_blocking_failure(self):
        guard_log = self.root / "codex-theme-guard.log"
        guard = (
            self.home
            / ".local"
            / "libexec"
            / "codex-theme-manager"
            / "codex-theme-guard"
        )
        guard.parent.mkdir(parents=True)
        self._write_executable(
            guard,
            """#!/usr/bin/env bash
printf '%s\n' "$*" > "${CODEX_THEME_GUARD_TEST_LOG:?}"
exit "${CODEX_THEME_GUARD_EXIT:-0}"
""",
        )

        result = self._install(
            CODEX_THEME_GUARD_TEST_LOG=str(guard_log),
            CODEX_THEME_GUARD_EXIT="23",
        )

        self.assertEqual(
            guard_log.read_text(encoding="utf-8").strip(),
            "--repair-state --repair-wrapper --check-wrapper --quiet",
        )
        self.assertIn(
            "warning: Codex theme manager self-heal failed",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
