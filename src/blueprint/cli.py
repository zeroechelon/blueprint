"""Blueprint CLI - Command line interface for Blueprint operations.

Provides commands for parsing, validating, and executing Blueprints.

Usage:
    blueprint parse <file>          Parse a Blueprint file and show structure
    blueprint validate <file>       Validate a Blueprint for errors
    blueprint execute <file>        Execute a Blueprint (dry-run by default)
    blueprint generate <goal>       Generate a Blueprint from a goal

Part of Blueprint Tier 4: CLI & UX.
"""
import json
import sys
from pathlib import Path
from typing import Optional

# Lazy imports to avoid loading heavy dependencies for --help
def get_parser():
    from blueprint.parser import parse_markdown, parse_json
    return parse_markdown, parse_json

def get_validator():
    from blueprint.validator import validate
    return validate

def get_executor():
    from blueprint.executor import BlueprintExecutor, ExecutionMode
    return BlueprintExecutor, ExecutionMode


def cmd_parse(filepath: str, verbose: bool = False) -> int:
    """Parse a Blueprint file and display its structure."""
    parse_markdown, parse_json = get_parser()
    
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        return 1
    
    try:
        content = path.read_text()
        
        if path.suffix == ".json":
            blueprint = parse_json(content)
        else:
            blueprint = parse_markdown(content)
        
        # Get title from metadata
        title = blueprint.metadata.title if blueprint.metadata else "Untitled"
        version = blueprint.blueprint_version or "N/A"
        
        # Count tasks
        total_tasks = sum(len(t.tasks) for t in blueprint.tiers)
        
        # Display summary
        print(f"Blueprint: {title}")
        print(f"Version: {version}")
        print(f"Tiers: {len(blueprint.tiers)}")
        print(f"Total Tasks: {total_tasks}")
        print()
        
        for tier in blueprint.tiers:
            status_icon = "✅" if tier.status.value == "complete" else "🔲"
            print(f"{status_icon} {tier.tier_id}: {tier.name}")
            for task in tier.tasks:
                task_icon = {"complete": "✅", "in_progress": "🔄", "blocked": "⛔"}.get(
                    task.status.value, "🔲"
                )
                deps = f" (deps: {', '.join(task.dependencies)})" if task.dependencies else ""
                print(f"    {task_icon} {task.task_id}: {task.name}{deps}")
                
                if verbose and task.interface:
                    print(f"        Input: {task.interface.input}")
                    print(f"        Output: {task.interface.output}")
        
        return 0
        
    except Exception as e:
        print(f"Error parsing Blueprint: {e}", file=sys.stderr)
        return 1


def cmd_validate(filepath: str, verbose: bool = False) -> int:
    """Validate a Blueprint and report errors."""
    parse_markdown, parse_json = get_parser()
    validate = get_validator()
    
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        return 1
    
    try:
        content = path.read_text()
        
        if path.suffix == ".json":
            blueprint = parse_json(content)
        else:
            blueprint = parse_markdown(content)
        
        result = validate(blueprint)
        
        # Count tasks from blueprint
        total_tasks = sum(len(t.tasks) for t in blueprint.tiers)
        
        if result.passed:
            print(f"✅ Blueprint is valid")
            print(f"   Tasks: {total_tasks}")
            print(f"   Tiers: {len(blueprint.tiers)}")
            if verbose:
                print(f"   Warnings: {len(result.warnings)}")
            return 0
        else:
            print(f"❌ Blueprint validation failed")
            print()
            for error in result.errors:
                severity_icon = "❌" if error.severity == "error" else "⚠️"
                location = f" [{error.task_id}]" if error.task_id else ""
                print(f"{severity_icon} {error.code}{location}: {error.message}")
            return 1
        
    except Exception as e:
        print(f"Error validating Blueprint: {e}", file=sys.stderr)
        return 1


def cmd_execute(filepath: str, dry_run: bool = True, verbose: bool = False) -> int:
    """Execute a Blueprint (dry-run by default)."""
    parse_markdown, parse_json = get_parser()
    validate = get_validator()
    BlueprintExecutor, ExecutionMode = get_executor()
    
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        return 1
    
    try:
        content = path.read_text()
        
        if path.suffix == ".json":
            blueprint = parse_json(content)
        else:
            blueprint = parse_markdown(content)
        
        # Validate first
        result = validate(blueprint)
        if not result.passed:
            print("❌ Blueprint validation failed. Run 'blueprint validate' for details.")
            return 1
        
        # Get title
        title = blueprint.metadata.title if blueprint.metadata else "Untitled"
        
        # Execute - mode is passed to execute(), not __init__()
        mode = ExecutionMode.DRY_RUN if dry_run else ExecutionMode.SEQUENTIAL
        executor = BlueprintExecutor(blueprint)
        
        print(f"{'[DRY RUN] ' if dry_run else ''}Executing Blueprint: {title}")
        print()
        
        exec_result = executor.execute(mode=mode)
        
        print()
        print(f"Execution {'simulated' if dry_run else 'complete'}")
        print(f"  Completed: {exec_result.completed_count}")
        print(f"  Failed: {exec_result.failed_count}")
        
        # Add skipped count if available
        skipped = getattr(exec_result, 'skipped_count', 0)
        if skipped:
            print(f"  Skipped: {skipped}")
        
        return 0 if exec_result.failed_count == 0 else 1
        
    except Exception as e:
        print(f"Error executing Blueprint: {e}", file=sys.stderr)
        return 1


def cmd_generate(goal: str, output: Optional[str] = None, verbose: bool = False) -> int:
    """Generate a Blueprint from a natural language goal."""
    try:
        from blueprint.generator import decompose_goal, infer_interfaces, assemble_blueprint
    except ImportError:
        print("Error: Generator requires 'llm' extras. Install with: pip install blueprint[llm]", 
              file=sys.stderr)
        return 1
    
    print(f"Generating Blueprint for: {goal}")
    print()
    
    try:
        # Decompose goal into tasks
        if verbose:
            print("📝 Decomposing goal into tasks...")
        tasks = decompose_goal(goal, return_dicts=True)
        if verbose:
            print(f"   Generated {len(tasks)} tasks")
        
        # Infer interfaces
        if verbose:
            print("🔗 Inferring interface contracts...")
        enriched = infer_interfaces(tasks)
        
        # Assemble Blueprint
        if verbose:
            print("📋 Assembling Blueprint...")
        markdown = assemble_blueprint(enriched, goal)
        
        # Output
        if output:
            path = Path(output)
            path.write_text(markdown)
            print(f"✅ Blueprint saved to: {output}")
        else:
            print("=" * 60)
            print(markdown)
        
        return 0
        
    except Exception as e:
        print(f"Error generating Blueprint: {e}", file=sys.stderr)
        return 1


def print_usage():
    """Print usage information."""
    print(__doc__)
    print("Commands:")
    print("  parse <file>          Parse and display Blueprint structure")
    print("  validate <file>       Validate Blueprint for errors")
    print("  execute <file>        Execute Blueprint (--run for real execution)")
    print("  generate <goal>       Generate Blueprint from goal (-o file to save)")
    print()
    print("Options:")
    print("  -h, --help            Show this help message")
    print("  -v, --verbose         Show detailed output")
    print("  --run                 Execute for real (default is dry-run)")
    print("  -o, --output <file>   Output file for generate command")


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for Blueprint CLI."""
    if argv is None:
        argv = sys.argv[1:]
    
    if not argv or argv[0] in ("-h", "--help"):
        print_usage()
        return 0
    
    command = argv[0]
    args = argv[1:]
    
    # Parse common flags
    verbose = "-v" in args or "--verbose" in args
    args = [a for a in args if a not in ("-v", "--verbose")]
    
    if command == "parse":
        if not args:
            print("Error: parse requires a file argument", file=sys.stderr)
            return 1
        return cmd_parse(args[0], verbose=verbose)
    
    elif command == "validate":
        if not args:
            print("Error: validate requires a file argument", file=sys.stderr)
            return 1
        return cmd_validate(args[0], verbose=verbose)
    
    elif command == "execute":
        if not args:
            print("Error: execute requires a file argument", file=sys.stderr)
            return 1
        dry_run = "--run" not in args
        filepath = [a for a in args if not a.startswith("-")][0]
        return cmd_execute(filepath, dry_run=dry_run, verbose=verbose)
    
    elif command == "generate":
        if not args:
            print("Error: generate requires a goal argument", file=sys.stderr)
            return 1
        
        # Parse output option
        output = None
        goal_parts = []
        i = 0
        while i < len(args):
            if args[i] in ("-o", "--output"):
                if i + 1 < len(args):
                    output = args[i + 1]
                    i += 2
                    continue
            goal_parts.append(args[i])
            i += 1
        
        goal = " ".join(goal_parts)
        return cmd_generate(goal, output=output, verbose=verbose)
    
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print_usage()
        return 1


if __name__ == "__main__":
    sys.exit(main())
