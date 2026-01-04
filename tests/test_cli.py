"""Tests for the Blueprint CLI."""
import pytest
from blueprint.cli import main, cmd_parse, cmd_validate


class TestCLIHelp:
    """Test help and usage."""
    
    def test_no_args_shows_usage(self, capsys):
        """No arguments should show usage."""
        result = main([])
        assert result == 0
        captured = capsys.readouterr()
        assert "Usage:" in captured.out or "Commands:" in captured.out
    
    def test_help_flag(self, capsys):
        """--help should show usage."""
        result = main(["--help"])
        assert result == 0
        captured = capsys.readouterr()
        assert "blueprint" in captured.out.lower()


class TestCLIErrors:
    """Test CLI error handling."""
    
    def test_unknown_command(self, capsys):
        """Unknown command should fail gracefully."""
        result = main(["unknown-command"])
        assert result == 1
        captured = capsys.readouterr()
        assert "Unknown command" in captured.err
    
    def test_parse_no_file(self, capsys):
        """parse without file should fail."""
        result = main(["parse"])
        assert result == 1
        captured = capsys.readouterr()
        assert "requires" in captured.err.lower()
    
    def test_validate_no_file(self, capsys):
        """validate without file should fail."""
        result = main(["validate"])
        assert result == 1
    
    def test_parse_missing_file(self, capsys):
        """parse with missing file should fail."""
        result = main(["parse", "nonexistent.md"])
        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()
