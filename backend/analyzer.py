import re
from typing import Dict, List, Any

def analyze_code(filename: str, content: str) -> Dict[str, Any]:
    """Performs static code analysis to calculate metrics and scan for security risks."""
    lines = content.splitlines()
    loc = 0
    num_functions = 0
    num_classes = 0
    warnings = []
    
    # Simple regex rules for analysis
    for line_num, line in enumerate(lines, 1):
        clean_line = line.strip()
        if not clean_line or clean_line.startswith("#"):
            continue
            
        loc += 1
        
        # Count functions and classes
        if clean_line.startswith("def "):
            num_functions += 1
        elif clean_line.startswith("class "):
            num_classes += 1
            
        # Scan for potential security risks
        # High Risk
        if "eval(" in clean_line:
            warnings.append({
                "line": line_num,
                "severity": "high",
                "message": "Use of unsafe eval() statement detected."
            })
        if "exec(" in clean_line:
            warnings.append({
                "line": line_num,
                "severity": "high",
                "message": "Use of unsafe exec() statement detected."
            })
        if "os.system(" in clean_line:
            warnings.append({
                "line": line_num,
                "severity": "high",
                "message": "Direct OS system call detected (subprocess preferred)."
            })
        if "shutil.rmtree('/')" in clean_line or "shutil.rmtree(\"/\")" in clean_line:
            warnings.append({
                "line": line_num,
                "severity": "danger",
                "message": "CAUTION: Potential workspace destruction code detected!"
            })
            
        # Medium Risk imports
        if re.search(r"import\s+(os|subprocess|shutil|sys)", clean_line):
            warnings.append({
                "line": line_num,
                "severity": "medium",
                "message": f"Module import '{clean_line}' has privileged execution rights."
            })
            
    # Calculate overall risk status
    has_danger = any(w["severity"] in ("high", "danger") for w in warnings)
    has_medium = any(w["severity"] == "medium" for w in warnings)
    
    risk_level = "Safe"
    if has_danger:
        risk_level = "Danger"
    elif has_medium:
        risk_level = "Warning"
        
    return {
        "filename": filename,
        "loc": loc,
        "functions": num_functions,
        "classes": num_classes,
        "risk": risk_level,
        "warnings": warnings
    }
