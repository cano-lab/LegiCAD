#!/usr/bin/env python3
"""
text_to_json_gui.py - Simple GUI for text-to-JSON building converter

A graphical interface for converting plain text building descriptions
to QBD JSON format for ArchEngine renderers.

Supports two layout modes:
- Simple: Basic grid-based room placement (built-in)
- Advanced: Full constraint-based solver with relationships (RevitMCP)
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import json
from pathlib import Path
import subprocess
import sys
import os

# Import the simple converter
from text_to_json import text_to_json, TextParser

# Try to import the advanced layout solver
ADVANCED_SOLVER_AVAILABLE = False
try:
    sys.path.insert(0, str(Path("X:/ARCH/Software/RevitMCP-roomlayout/server")))
    from qbd_layout_generator import export_for_archengine
    ADVANCED_SOLVER_AVAILABLE = True
except ImportError as e:
    print(f"Advanced solver not available: {e}")


class TextToJsonApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ArchEngine - Text to JSON Converter")
        self.root.geometry("1200x800")
        self.root.minsize(800, 600)

        # Set icon if available
        try:
            self.root.iconbitmap(default='')
        except:
            pass

        # Configure grid
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        # Current JSON result
        self.current_json = None
        self.output_dir = Path(__file__).parent.parent.parent / "Shared" / "TestData" / "output"

        self._create_widgets()
        self._create_menu()

        # Set default example text
        self.set_example()

    def _create_widgets(self):
        """Create all UI widgets"""

        # Top frame - Title and description
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.grid(row=0, column=0, sticky="ew")

        title_label = ttk.Label(
            top_frame,
            text="Building Description to JSON Converter",
            font=('Segoe UI', 16, 'bold')
        )
        title_label.pack(anchor="w")

        desc_label = ttk.Label(
            top_frame,
            text="Enter a plain text description of a building and convert it to structured JSON for ArchEngine.",
            font=('Segoe UI', 10)
        )
        desc_label.pack(anchor="w", pady=(5, 0))

        # Layout mode selector
        mode_frame = ttk.Frame(top_frame)
        mode_frame.pack(anchor="w", pady=(10, 0))

        ttk.Label(mode_frame, text="Layout Mode:", font=('Segoe UI', 10)).pack(side=tk.LEFT)

        self.layout_mode = tk.StringVar(value="advanced" if ADVANCED_SOLVER_AVAILABLE else "simple")

        self.simple_radio = ttk.Radiobutton(
            mode_frame, text="Simple (Grid)",
            variable=self.layout_mode, value="simple"
        )
        self.simple_radio.pack(side=tk.LEFT, padx=(10, 5))

        self.advanced_radio = ttk.Radiobutton(
            mode_frame, text="Advanced (Constraint Solver)",
            variable=self.layout_mode, value="advanced",
            state=tk.NORMAL if ADVANCED_SOLVER_AVAILABLE else tk.DISABLED
        )
        self.advanced_radio.pack(side=tk.LEFT, padx=(0, 10))

        if not ADVANCED_SOLVER_AVAILABLE:
            ttk.Label(mode_frame, text="(RevitMCP solver not found)",
                     font=('Segoe UI', 9), foreground='gray').pack(side=tk.LEFT)

        # Main paned window
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

        # Left panel - Input
        left_frame = ttk.LabelFrame(paned, text="Input Description", padding="5")
        paned.add(left_frame, weight=1)

        # Input text area
        self.input_text = scrolledtext.ScrolledText(
            left_frame,
            wrap=tk.WORD,
            font=('Consolas', 11),
            height=20
        )
        self.input_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Button frame
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X)

        # Buttons
        self.convert_btn = ttk.Button(
            btn_frame,
            text="Convert to JSON",
            command=self.convert,
            style='Accent.TButton'
        )
        self.convert_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.clear_btn = ttk.Button(
            btn_frame,
            text="Clear",
            command=self.clear_input
        )
        self.clear_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.example_btn = ttk.Button(
            btn_frame,
            text="Load Example",
            command=self.set_example
        )
        self.example_btn.pack(side=tk.LEFT, padx=(0, 5))

        # Quick examples dropdown
        ttk.Label(btn_frame, text="Quick:").pack(side=tk.LEFT, padx=(15, 5))
        self.quick_var = tk.StringVar()
        self.quick_combo = ttk.Combobox(
            btn_frame,
            textvariable=self.quick_var,
            values=[
                "1 bed apartment 600 sqft",
                "2 bed 1 bath house 1000 sqft",
                "3 bed 2 bath modern 1500 sqft",
                "4 bed 2.5 bath with office 2200 sqft",
                "3 bed ranch with 2 car garage 1800 sqft",
                "5 bed colonial 3000 sqft with study"
            ],
            width=35
        )
        self.quick_combo.pack(side=tk.LEFT, padx=(0, 5))
        self.quick_combo.bind("<<ComboboxSelected>>", self.load_quick_example)

        # Right panel - Output
        right_frame = ttk.LabelFrame(paned, text="JSON Output", padding="5")
        paned.add(right_frame, weight=1)

        # Output text area
        self.output_text = scrolledtext.ScrolledText(
            right_frame,
            wrap=tk.NONE,
            font=('Consolas', 10),
            height=20
        )
        self.output_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Output buttons
        out_btn_frame = ttk.Frame(right_frame)
        out_btn_frame.pack(fill=tk.X)

        self.save_btn = ttk.Button(
            out_btn_frame,
            text="Save JSON",
            command=self.save_json,
            state=tk.DISABLED
        )
        self.save_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.copy_btn = ttk.Button(
            out_btn_frame,
            text="Copy to Clipboard",
            command=self.copy_json,
            state=tk.DISABLED
        )
        self.copy_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.gen_plans_btn = ttk.Button(
            out_btn_frame,
            text="Generate Plans (SVG)",
            command=self.generate_plans,
            state=tk.DISABLED
        )
        self.gen_plans_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.open_folder_btn = ttk.Button(
            out_btn_frame,
            text="Open Output Folder",
            command=self.open_output_folder
        )
        self.open_folder_btn.pack(side=tk.LEFT, padx=(0, 5))

        # Bottom frame - Status and summary
        bottom_frame = ttk.Frame(self.root, padding="10")
        bottom_frame.grid(row=2, column=0, sticky="ew")

        # Status bar
        self.status_var = tk.StringVar(value="Ready. Enter a building description and click 'Convert to JSON'.")
        self.status_label = ttk.Label(
            bottom_frame,
            textvariable=self.status_var,
            font=('Segoe UI', 9)
        )
        self.status_label.pack(side=tk.LEFT)

        # Summary frame
        self.summary_frame = ttk.Frame(bottom_frame)
        self.summary_frame.pack(side=tk.RIGHT)

        self.summary_var = tk.StringVar(value="")
        self.summary_label = ttk.Label(
            self.summary_frame,
            textvariable=self.summary_var,
            font=('Segoe UI', 9, 'bold')
        )
        self.summary_label.pack(side=tk.RIGHT)

    def _create_menu(self):
        """Create menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open Description...", command=self.open_file)
        file_menu.add_command(label="Save JSON As...", command=self.save_json_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        # Edit menu
        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Clear Input", command=self.clear_input)
        edit_menu.add_command(label="Copy JSON", command=self.copy_json)

        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Generate Floor Plan SVG", command=self.generate_plans)
        tools_menu.add_command(label="Open in UE5 Viewer", command=self.open_in_viewer, state=tk.DISABLED)
        tools_menu.add_separator()
        tools_menu.add_command(label="Open Output Folder", command=self.open_output_folder)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Syntax Help", command=self.show_help)
        help_menu.add_command(label="About", command=self.show_about)

    def convert(self):
        """Convert input text to JSON"""
        text = self.input_text.get("1.0", tk.END).strip()

        if not text:
            messagebox.showwarning("No Input", "Please enter a building description.")
            return

        try:
            mode = self.layout_mode.get()
            self.status_var.set(f"Converting ({mode} mode)...")
            self.root.update()

            if mode == "advanced" and ADVANCED_SOLVER_AVAILABLE:
                # Use advanced constraint-based solver
                result = self._convert_advanced(text)
            else:
                # Use simple grid-based layout
                result = text_to_json(text)

            self.current_json = result

            # Format and display JSON
            json_str = json.dumps(result, indent=2)
            self.output_text.delete("1.0", tk.END)
            self.output_text.insert("1.0", json_str)

            # Enable buttons
            self.save_btn.config(state=tk.NORMAL)
            self.copy_btn.config(state=tk.NORMAL)
            self.gen_plans_btn.config(state=tk.NORMAL)

            # Update summary
            summary = result.get("summary", {})
            summary_text = (
                f"Rooms: {summary.get('rooms_placed', 0)} | "
                f"Walls: {summary.get('total_walls', 0)} | "
                f"Doors: {summary.get('doors', 0)} | "
                f"Windows: {summary.get('windows', 0)} | "
                f"Area: {result.get('sqft', 0)} sqft ({result.get('sqm', 0)} sqm)"
            )
            self.summary_var.set(summary_text)

            mode_label = "Advanced" if mode == "advanced" else "Simple"
            self.status_var.set(f"Conversion successful! ({mode_label}) Building ID: {result.get('building_id', 'N/A')}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("Conversion Error", f"Failed to convert text:\n\n{str(e)}")
            self.status_var.set(f"Error: {str(e)}")

    def _convert_advanced(self, text: str) -> dict:
        """Convert using advanced constraint-based solver"""
        # First parse the text to extract parameters
        parser = TextParser()
        parsed = parser.parse(text)

        # Convert to QBD answers format expected by qbd_layout_generator
        answers = {
            "sqft": str(parsed.get("sqft", 1200)),
            "bedrooms": str(len([r for r in parsed["rooms"]
                               if r.room_type.value in ["bedroom", "master_bedroom"]])),
            "bathrooms": str(len([r for r in parsed["rooms"]
                                if r.room_type.value in ["bathroom", "master_bath", "half_bath"]])),
            "garage": parsed.get("garage", "none"),
            "style": parsed.get("style", "modern"),
            "special_rooms": [r.room_type.value for r in parsed["rooms"]
                            if r.room_type.value in ["office", "laundry", "mudroom", "pantry",
                                                      "dining", "family_room", "bonus_room"]]
        }

        # Call the advanced solver
        result = export_for_archengine(answers)

        # Add roof info from our parser (advanced solver may not have it)
        if "roofs" not in result or not result.get("roofs"):
            result["roofs"] = self._generate_roof(result, parsed)

        # Store original description
        if "qbd_answers" not in result:
            result["qbd_answers"] = {}
        result["qbd_answers"]["description"] = text

        return result

    def _generate_roof(self, layout: dict, parsed: dict) -> list:
        """Generate roof data from building footprint"""
        width = layout.get("width", 12000)
        depth = layout.get("depth", 9000)
        wall_height = 2700

        roof_type = parsed.get("roof_type", "gable")
        pitch = parsed.get("roof_pitch", 6)
        material = parsed.get("roof_material", "asphalt_shingle")
        overhang = 600  # mm

        # Calculate ridge height (pitch = rise per 12" run)
        if roof_type in ["gable", "hip"]:
            # For gable, ridge runs along length, height based on half the depth
            half_span = (depth / 2) / 304.8  # Convert mm to feet
            ridge_height = wall_height + (half_span * pitch * 25.4)  # Convert back to mm
        else:
            ridge_height = wall_height + 300  # Minimal slope for flat

        roof = {
            "id": "roof_1",
            "type": roof_type,
            "pitch": pitch,
            "overhang": overhang,
            "material": material,
            "level_name": "Roof Level",
            "ridges": [],
            "surfaces": [],
            "dormers": [],
            "skylights": []
        }

        if roof_type == "gable":
            # Ridge runs along length (X axis)
            roof["ridges"] = [{
                "id": "ridge_1",
                "start_point": [-overhang, depth / 2, ridge_height],
                "end_point": [width + overhang, depth / 2, ridge_height],
                "height": ridge_height - wall_height
            }]
            # Two surfaces: front and back
            roof["surfaces"] = [
                {
                    "id": "surface_south",
                    "vertices": [
                        [-overhang, -overhang, wall_height],
                        [width + overhang, -overhang, wall_height],
                        [width + overhang, depth / 2, ridge_height],
                        [-overhang, depth / 2, ridge_height]
                    ],
                    "pitch": pitch,
                    "orientation": "south"
                },
                {
                    "id": "surface_north",
                    "vertices": [
                        [-overhang, depth / 2, ridge_height],
                        [width + overhang, depth / 2, ridge_height],
                        [width + overhang, depth + overhang, wall_height],
                        [-overhang, depth + overhang, wall_height]
                    ],
                    "pitch": pitch,
                    "orientation": "north"
                }
            ]
        elif roof_type == "hip":
            # Hip has four surfaces meeting at ridge points
            roof["ridges"] = [{
                "id": "ridge_1",
                "start_point": [depth / 2, depth / 2, ridge_height],
                "end_point": [width - depth / 2, depth / 2, ridge_height],
                "height": ridge_height - wall_height
            }]

        return [roof]

    def clear_input(self):
        """Clear input text area"""
        self.input_text.delete("1.0", tk.END)
        self.status_var.set("Input cleared.")

    def set_example(self):
        """Set example description"""
        example = """3 bedroom 2 bathroom modern house with approximately 1800 square feet.

Include a 2-car garage, home office, and open concept living/kitchen area.

Style: contemporary with clean lines."""

        self.input_text.delete("1.0", tk.END)
        self.input_text.insert("1.0", example)
        self.status_var.set("Example loaded. Click 'Convert to JSON' to process.")

    def load_quick_example(self, event=None):
        """Load selected quick example"""
        text = self.quick_var.get()
        if text:
            self.input_text.delete("1.0", tk.END)
            self.input_text.insert("1.0", text)
            self.status_var.set("Quick example loaded.")

    def save_json(self):
        """Save JSON to default location"""
        if not self.current_json:
            return

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.output_dir / "generated_building.json"

            with open(output_path, 'w') as f:
                json.dump(self.current_json, f, indent=2)

            self.status_var.set(f"Saved to: {output_path}")
            messagebox.showinfo("Saved", f"JSON saved to:\n{output_path}")

        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save:\n{str(e)}")

    def save_json_as(self):
        """Save JSON to chosen location"""
        if not self.current_json:
            messagebox.showwarning("No Data", "No JSON to save. Convert a description first.")
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(self.output_dir),
            initialfile="generated_building.json"
        )

        if filepath:
            try:
                with open(filepath, 'w') as f:
                    json.dump(self.current_json, f, indent=2)
                self.status_var.set(f"Saved to: {filepath}")
            except Exception as e:
                messagebox.showerror("Save Error", f"Failed to save:\n{str(e)}")

    def copy_json(self):
        """Copy JSON to clipboard"""
        if not self.current_json:
            return

        json_str = json.dumps(self.current_json, indent=2)
        self.root.clipboard_clear()
        self.root.clipboard_append(json_str)
        self.status_var.set("JSON copied to clipboard.")

    def generate_plans(self):
        """Generate floor plan SVG"""
        if not self.current_json:
            messagebox.showwarning("No Data", "No JSON to process. Convert a description first.")
            return

        try:
            # Save JSON first
            self.output_dir.mkdir(parents=True, exist_ok=True)
            json_path = self.output_dir / "generated_building.json"

            with open(json_path, 'w') as f:
                json.dump(self.current_json, f, indent=2)

            # Run plan generator
            script_dir = Path(__file__).parent
            gen_script = script_dir / "generate_plans.py"

            self.status_var.set("Generating floor plans...")
            self.root.update()

            result = subprocess.run(
                [sys.executable, str(gen_script), str(json_path)],
                capture_output=True,
                text=True,
                cwd=str(script_dir)
            )

            if result.returncode == 0:
                floor_plan = self.output_dir / "floor_plan_generated.svg"
                roof_plan = self.output_dir / "roof_plan_generated.svg"

                msg = f"Plans generated:\n\n- Floor plan: {floor_plan.name}\n- Roof plan: {roof_plan.name}"
                self.status_var.set("Plans generated successfully!")

                # Ask to open
                if messagebox.askyesno("Plans Generated", f"{msg}\n\nOpen floor plan?"):
                    os.startfile(str(floor_plan))
            else:
                messagebox.showerror("Generation Error", f"Failed to generate plans:\n{result.stderr}")
                self.status_var.set("Plan generation failed.")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate plans:\n{str(e)}")
            self.status_var.set(f"Error: {str(e)}")

    def open_output_folder(self):
        """Open output folder in file explorer"""
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.output_dir))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open folder:\n{str(e)}")

    def open_file(self):
        """Open description from file"""
        filepath = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )

        if filepath:
            try:
                with open(filepath, 'r') as f:
                    text = f.read()
                self.input_text.delete("1.0", tk.END)
                self.input_text.insert("1.0", text)
                self.status_var.set(f"Loaded: {filepath}")
            except Exception as e:
                messagebox.showerror("Open Error", f"Failed to open file:\n{str(e)}")

    def open_in_viewer(self):
        """Open in UE5 viewer (placeholder)"""
        messagebox.showinfo("UE5 Viewer", "UE5 viewer integration coming soon.\n\nFor now, open the UE5 project and load the JSON file manually.")

    def show_help(self):
        """Show syntax help"""
        help_text = """BUILDING DESCRIPTION SYNTAX

The converter understands natural language descriptions. Here are some examples:

ROOMS:
- "3 bedroom" or "3 bed" or "3 br"
- "2 bathroom" or "2 bath" or "2.5 bath" (half bath)
- "with office" or "with study"
- "with laundry" or "mudroom"
- "with pantry"
- "dining room"
- "great room" or "family room"

SIZE:
- "1800 sqft" or "1800 square feet"
- "150 sqm" or "150 square meters"

STYLE:
- "modern", "contemporary", "traditional"
- "craftsman", "colonial", "ranch"
- "farmhouse", "mediterranean"

GARAGE:
- "with garage" or "1 car garage"
- "2 car garage" or "3 car garage"
- "no garage"

STORIES:
- "2 story" or "two story"
- "single story" or "ranch"

EXAMPLES:
- "3 bed 2 bath modern house 1800 sqft with 2 car garage"
- "small 1 bedroom apartment 600 sqft"
- "4 bed 2.5 bath colonial with office and mudroom 2500 sqft"
"""

        help_window = tk.Toplevel(self.root)
        help_window.title("Syntax Help")
        help_window.geometry("500x600")

        text = scrolledtext.ScrolledText(help_window, wrap=tk.WORD, font=('Consolas', 10))
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text.insert("1.0", help_text)
        text.config(state=tk.DISABLED)

    def show_about(self):
        """Show about dialog"""
        about_text = """ArchEngine Text to JSON Converter

Version 1.0

Converts plain text building descriptions to structured JSON
format compatible with ArchEngine UE5 viewer and plan generators.

Part of the ArchEngine Suite for architectural visualization.

(c) 2024 ArchEngine Project"""

        messagebox.showinfo("About", about_text)


def main():
    """Main entry point"""
    root = tk.Tk()

    # Try to apply a modern theme
    try:
        style = ttk.Style()
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        elif 'clam' in style.theme_names():
            style.theme_use('clam')
    except:
        pass

    app = TextToJsonApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
