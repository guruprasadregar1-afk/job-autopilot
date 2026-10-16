import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def test_no_raw_playwright_page_calls():
    """
    Ensures that all platform code and browser code uses SafePage / SafeLocator
    safe_* methods and NEVER calls raw Playwright methods outside policy.py:
    .click, .fill, .check, .goto, .press, .type, .set_input_files, .evaluate,
    .dispatch_event, .select_option, .set_checked, .uncheck, .tap, .dblclick,
    .press_sequentially, .mouse, .keyboard, .route, .evaluate_handle,
    .eval_on_selector, .add_script_tag, .new_page, or .on on ANY object.
    """
    target_dirs = [PROJECT_ROOT / "src" / "platforms"]
    python_files = [PROJECT_ROOT / "src" / "browser.py"]
    for d in target_dirs:
        if d.exists():
            python_files.extend(d.glob("*.py"))
            
    forbidden_methods = {
        "click", "fill", "check", "goto", "press", "type",
        "set_input_files", "evaluate", "dispatch_event",
        "select_option", "set_checked", "uncheck", "tap", "dblclick",
        "press_sequentially", "mouse", "keyboard", "route",
        "evaluate_handle", "eval_on_selector", "add_script_tag",
        "new_page", "on"
    }
    class CallVisitor(ast.NodeVisitor):
        def __init__(self, filename: str):
            self.filename = filename
            self.current_func = None
            self.violations = []

        def visit_FunctionDef(self, node):
            old = self.current_func
            self.current_func = node.name
            self.generic_visit(node)
            self.current_func = old

        def visit_AsyncFunctionDef(self, node):
            old = self.current_func
            self.current_func = node.name
            self.generic_visit(node)
            self.current_func = old

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_methods:
                # Documented Narrow Exemption:
                # BrowserContext.new_page() is exclusively permitted inside cleanup_startup_tabs
                # in src/browser.py to open a pristine blank tab before closing all restored tabs.
                is_startup_cleanup_exemption = (
                    self.filename == "browser.py"
                    and self.current_func == "cleanup_startup_tabs"
                    and node.func.attr == "new_page"
                )
                if not is_startup_cleanup_exemption:
                    target_obj = ast.unparse(node.func.value) if hasattr(ast, "unparse") else getattr(node.func.value, "id", "object")
                    self.violations.append(f"{self.filename}:{node.lineno} calls forbidden raw .{node.func.attr}() on '{target_obj}'")
            self.generic_visit(node)

    violations = []
    for py_file in python_files:
        if py_file.name == "__init__.py":
            continue
        code = py_file.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=str(py_file))
        visitor = CallVisitor(py_file.name)
        visitor.visit(tree)
        violations.extend(visitor.violations)

    assert not violations, f"Detected forbidden raw Playwright method calls outside policy.py: {violations}"
