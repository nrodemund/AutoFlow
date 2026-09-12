# AutoFlow

A directly runnable Python app with a local Blueprint-style node editor for desktop
automation. Windows x64 Python, Pillow, NumPy and OpenCV binaries are included.

## Start

Double-click **start.cmd**. The editor opens at **http://127.0.0.1:8765**.
Keep the starter window open; Ctrl+C shuts down the server. No Python install,
Node.js, build, account or internet connection is needed. Windows 10/11 x64 is
the supported bundled platform. PowerShell users can also run `./start.ps1`.

The editor reopens the **last saved project** at startup. On first use it opens
an Add (Int) -> Print demonstration. Click Run to print `5` in Output Log.
Opening a graph never executes it automatically.

```powershell
.\autoflow.cmd editor
.\autoflow.cmd editor --port 8766 --no-browser
.\autoflow.cmd nodes
.\autoflow.cmd run examples\add-print.json
.\autoflow.cmd validate examples\wait-for-screen.json
.\autoflow.cmd run examples\screen-flow.json --simulate-screen
.\test.cmd
```

## Editor controls

- **Add:** click a node in the searchable library, or drag it to a position on the canvas.
- **Move:** drag a node header. Drag empty canvas to pan; scroll to zoom; F to fit.
- **Connect:** drag an output pin onto an input pin, or click the two pins.
  White pins control execution; colored pins carry typed data. Outputs may feed
  several data inputs. Each input accepts one data source. Escape cancels a wire.
- **Values:** unconnected inputs hold Python values: bool, integer, float, string, bytes, set and dict; custom values use reference pins
  or texture paths directly. Tab/Enter commits edits. Connected pins show their
  source. Add (Int) is pure: it evaluates when another node reads its result.
- **Disconnect:** Alt-click/right-click a pin, or double-click/right-click a wire.
- **Details:** select a node to change its title, entry status or parameter bindings.
  On narrower windows use the Details button to open the panel.
- **Delete / undo:** select a node and press Delete. Ctrl+Z / Ctrl+Y undo and redo.
- **Run / Stop:** execute the current project and read Print output/errors in the
  integrated Output Log. Stop cancels waits and stops at execution boundaries.
  A capture/match already in progress finishes before cancellation is observed.

## Save, load and assets

Save or Ctrl+S writes `projects/<filename>.json`. Change the filename before saving
to keep another copy. All graphs, connections, literals and node positions are
preserved. `projects/.editor-state.json` records the last saved filename across
browser refreshes and Python restarts. Incomplete drafts can be saved; Run reports
invalid graph structure. Unsaved changes are not automatically saved.

Open lists local projects and bundled examples. Import JSON loads a graph from
disk. Save an imported/example graph to make it the startup project. Export
downloads a JSON copy without changing the startup project. Assets are separate;
copy the referenced files with exported JSON when moving a project.

Paths in web-editor runs resolve relative to `projects/`. Texture Browse and
From clipboard store actual PNG assets in `projects/assets/` and fill the pin
with their relative path. CLI runs resolve paths relative to their input JSON.
Texture inputs include a tiny thumbnail; click it to open a larger preview.
Hover over the enlarged image to read X/Y in original texture pixels, starting
at (0, 0) in its top-left corner. These offsets can later be added to match X/Y.
Close the preview with Escape, the close button, or a click outside the dialog.
The bundled CSV example is adjusted to `../examples/people.csv` when opened through
the editor's Examples list. For manually imported graphs, adjust relative paths
or copy their files into `projects/`.

## Screen nodes

**FindOnScreen** and **IfOnScreen** capture the Windows virtual desktop and locate
the supplied texture. They expose Found / Not found execution pins and `found`
and `point` data outputs. A Point contains integer X/Y coordinates for the matched image's **top-left physical pixels**,
including negative coordinates on monitors left/above the primary monitor.
Missing/unreadable texture files produce a clear error instead of pretending the
image was not found.

**IsOnScreen** is a pure node with a `found` boolean output and **no flow pins**.
Every read captures and evaluates the current screen. Connect it to a boolean
input such as Wait Until's Condition.

All three nodes accept a texture reference and integer Confidence percent (default 97).
Matching compares RGB pixels at the original template size. The score is
`1 - RMS pixel error / 255`, not a statistical probability. Fully transparent
pixels are ignored; fully transparent images are rejected. Distinctive, tightly
cropped screenshots work best. Changing UI scale, font rendering, theme or zoom
may require a new crop; there is no scale-invariant/OCR matching yet.

**From clipboard** reads an actual Windows clipboard image when clicked. Use
Win+Shift+S to capture a small UI feature, then click From clipboard on a texture
input. Copying a filename or text is not the same as copying an image; the editor
reports this case. Clipboard images are copied into the project, so subsequent
clipboard changes do not change saved graphs.

Screen matching and input actions are live in the web editor and CLI.
`--simulate-screen` disables screen capture and all input/clipboard actions for
CLI demonstrations. The Engine API defaults to a simulation
backend unless a real `WindowsScreen(base_dir)` is supplied.

## FindPointOnScreen and desktop input

**FindPointOnScreen** finds a texture, adds `offset_x` and `offset_y`, and returns
the resulting Point through Found / Not found branches. Both offsets are integer
inputs: type values, connect pins, or open the texture thumbnail and click a pixel
to set them. Picking a pixel replaces any offset pin connections and supports Undo.
The hover coordinates are original texture pixels, even when the preview is enlarged.

- **Click:** move to Point and perform a real left click.
- **Mouse Move:** move to Point without clicking.
- **Drag:** left-button drag from Start Point to End Point over Duration ms.
- **Key Press:** send a key/chord such as `enter`, `ctrl+a`, `shift+tab` or `F5`.
  Letters, digits, Ctrl/Shift/Alt/Win, arrows and common navigation keys are supported.
- **Copy:** send Ctrl+C to the focused app and return its Unicode clipboard text.
  An unchanged clipboard or non-text selection reports an error.
- **Find Text on Screen (OCR):** local Windows OCR of the rectangle between two
  Point inputs, `start` and `end`, in physical desktop pixels. Either corner order
  works, including negative coordinates on secondary monitors. Wire the exact
  desired row into `text`, for example `Enoxaparin 40 mg s.c. 21:00`. Matching is
  whole-line and case-sensitive; only whitespace is normalized. It does not
  accept partial text or substitute similar numbers. Output `point` is the center
  of the first matching line (top to bottom, then left to right). Connect the
  `found` execution branch and `point` to Click; `not_found` returns a null point.
  The rectangle must be inside the desktop and include the full text of each row.
  Only visible content is recognized; the node does not scroll. Blank `language`
  uses Windows language settings; `de-DE` selects German explicitly. Missing OCR
  language packs produce an error. OCR can misread text; exact comparison is
  against the recognized text. The standalone runtime includes the bindings;
  a separate Python install needs `pip install .[ocr]` on Windows.
- **Paste:** send Ctrl+V using the current clipboard. Disable Use clipboard to
  type Text directly without reading or changing the clipboard (Text can be wired
  from Copy or another node). This prevents concurrent clipboard changes from
  substituting other content. Direct text uses Unicode keyboard input; the target
  app controls how tabs and line breaks are handled.

Input goes to the active Windows application. Use a Wait node to give yourself
time to switch windows, or click the target before typing. Actions execute only
when Run reaches them. Stop interrupts a drag and releases its mouse button;
keyboard chords release their modifiers. Windows may reject input directed at
an elevated app from a non-elevated AutoFlow process.

If capture reports an entirely black image, run `start.cmd` on your normal,
unlocked Windows desktop. An agent sandbox can return black pixels even though
the image is visible to you. AutoFlow reports this as a capture error rather than
following Not found/False; reducing confidence cannot fix unavailable screen data.

## Wait Until example

Open **wait-for-screen.json** from the Examples list. Supply the IsOnScreen
texture using Browse, From clipboard or a path. The example is wired as follows:

```text
Start --execution--> Wait Until --True--> Print success
                         |      --False-> Print timeout
                         +------Loop----> Print attempt
IsOnScreen --found bool-->Condition
```

The default Loop interval is **500 ms** and Max attempts is **5**.
The first attempt is immediate. Each attempt:

1. Sets the 1-based `attempt` output and executes the Loop branch.
2. Evaluates Condition afresh (including connected pure IsOnScreen nodes).
3. Follows True and stops if the condition is true.
4. Otherwise waits until the next interval, or follows False after the fifth check.

Intervals are measured between attempt starts; slow capture or Loop work can
make an attempt take longer than the requested interval. Normally five failed
checks occur around 0, 500, 1000, 1500 and 2000 ms. The Loop body should end with
an unconnected execution output, returning to Wait Until; do not wire it back
to Wait Until. Condition can also be a literal boolean or an output produced by
an execution node inside Loop (e.g. IfOnScreen). Loop runs even for an immediately
true condition. The final `attempt` and `matched` outputs are available to the
True/False branches. A literal false condition retries to the limit; a literal
true condition succeeds on the first attempt.

## Integer math, points and Wait Until A/B

Numeric node pins use **integer**, not number. Wait durations are integer
milliseconds, and screen confidence is an integer percentage from 1 to 100.
The math library includes Add, Subtract, Multiply, Divide, Modulo, Min and Max.
Division truncates toward zero; modulo uses the sign of A. Division/modulo by zero
report an error. Pure arithmetic nodes evaluate when their outputs are read.

**Point** is `{ "x": 0, "y": 0 }`, with both fields integers. Unconnected Point
inputs have inline X/Y editors. Make Point combines integers into a Point;
Break Point exposes a Point's X and Y. Screen searches output a Point (null when
not found). Click accepts a Point. Offset adds an offset Point to a base Point.

**Wait Until A/B** reevaluates boolean inputs A and B at each integer interval
(default 500 ms), and exits through A, B or Timeout (default 5000 ms). It checks
immediately, evaluates A first and short-circuits if A is true, so A has priority
when both are true. The timeout is a time limit, not an attempt count; a capture
already in progress completes before timeout/cancellation is observed. Attempt
and elapsed_ms outputs describe the final check. Open `wait-ab.json` for a
runnable B-branch example; connect IsOnScreen boolean outputs to A/B to poll UI.

Older graphs are upgraded in memory on load/import: seconds become milliseconds,
fractional confidence becomes percent, and old X/Y connections receive Make/Break
Point adapters. Files are not rewritten until Save. New graphs include
`schema_revision: 2`; when hand-authoring JSON, include this marker to use the new
pin names and units directly.

## Function graph configuration

Use **+** beside My Blueprint to create a function. **Graph settings** edits
its name, description, typed parameters and typed return values using row editors.
Parameters create **Parameter** nodes. A **Return** node exposes an input for
each named return value and ends the function immediately, including inside a
loop. Wire the execution path to Return. Zero or multiple return values are
supported. Graph settings can rename or delete functions; remove external calls
before deletion. The main graph cannot be deleted.

Drag a function name from My Blueprint into the canvas, or click its adjacent
**+**, to create a **Call Function** node. Inputs and outputs follow the function
signature. Renaming parameters, return values or the function updates its call
nodes and references. Added pins receive type defaults; removed return bindings
are disconnected. Changing a type may require reconnecting incompatible values.
The legacy CallFunction node (graph name + arguments dict, result dict) remains
supported for older projects. Calls retain depth and execution limits.

Open `functions-strings.json` to see a function returning a greeting and a length.

A project's JSON has `version: 1`, `main` and a `graphs` map. Each graph contains
`entry`, `parameters`, `outputs` and a `nodes` map. Nodes contain `type`, `inputs`,
optional `next` (execution output -> target node ID) and `position: [x, y]`.

Input bindings support literals and nested objects/arrays:

```json
{"ref": ["add", "result"]}
{"param": "row"}
{"row": {"ref": ["each", "item"]}}
```

Objects containing exactly `ref` or `param` are reserved binding syntax.
Data from execution nodes must already have been produced. Pure nodes evaluate
on demand. Cyclic pure connections fail explicitly. ForEach runs Body for each
item, then Completed; item/body state is scoped to the iteration. Pin metadata
supports the editor's connection compatibility checks; full static graph type
analysis and object-field selection are future extensions.

## Modular Python nodes

Add a file under `autoflow/nodes/`, export `NODES`, then restart Python:

```python
from autoflow.registry import NodeType

def multiply(context, node_id, inputs):
    return {"result": inputs["a"] * inputs["b"]}, None

NODES = [NodeType(
    name="MultiplyInt", title="Multiply (Int)", category="Math",
    inputs={"a": "integer", "b": "integer"},
    outputs={"result": "integer"}, flows=(), execute=multiply,
    defaults={"a": 2, "b": 3}, pure=True,
)]
```

An execution node instead declares `flows=("then",)` and returns `(outputs,
"then")`. The editor discovers its pins and defaults from this metadata. Duplicate
node type names are rejected. A node that reevaluates an input, such as Wait Until,
can declare `deferred_inputs=("condition",)` and call `context.resolve()` at the
appropriate moment. Use `context.check()` during long loops and
`context.engine.cancel.wait(seconds)` for interruptible waits. Node modules are
trusted Python code, not sandboxed plugins.

## Project layout and development

```text
autoflow/engine.py       Graph persistence, validation and execution
autoflow/registry.py     Node discovery and metadata
autoflow/nodes/          Modular core, demo, screen and polling nodes
autoflow/server.py       Local API, run worker, persistence and console events
autoflow/screen.py       Windows capture, OpenCV matching and clipboard assets
autoflow/web/            HTML/CSS/JS editor, no external assets or build step
examples/               Add/Print, CSV/functions, screen and polling graphs
tests/                  Engine, HTTP API, image-matching and polling tests
projects/               User saves and texture assets (ignored by Git)
runtime/                Python, dependency binaries, original archives and licenses
scripts/                Reproducible dependency bundling script
```

The server binds only to `127.0.0.1` and checks Host/Origin for browser requests.
A normal Python 3.11+ development installation can use `pip install -e .` and
`python -m autoflow editor`; live capture/clipboard currently target Windows.
The embedded runtime has all required packages; do not run pip inside it.

Run `test.cmd` for the complete suite. Browser checks covered inline values,
dragging, pin disconnection/reconnection, Print output and reopening a saved graph.
Tests cover pure-node chains/cycles, functions, HTTP persistence/restart behavior,
matching with synthetic images and multi-monitor origins, clipboard image/error
handling, repeated condition evaluation, retry cadence and cancellation.

Runtime sources, hashes and license locations are in [runtime/README.md](runtime/README.md).
Capture behavior follows [Pillow ImageGrab](https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html);
matching uses [OpenCV template matching](https://docs.opencv.org/4.13.0/de/da9/tutorial_template_matching.html).

## Datasets

Use **Datasets +** to create a JSON table, or **Import CSV / Excel** to load a
UTF-8 CSV or `.xlsx` workbook. Column types are inferred; leading-zero values stay strings.
Excel imports the first sheet; the LoadDataset node can select a sheet by name.
Excel formulas import their last cached value, not a newly calculated result.
Dates become ISO text. Legacy `.xls` is not supported.

Open a dataset to edit cells, choose bool/integer/float/string/bytes types per column, add columns
or rows, delete rows, search all columns, and click headings to sort. Tables show
100 rows per page. Sorting changes actual row order. Row indices start at **0**.
Undo reverses edits. CSV and Excel buttons download the current table. CSV has
no declared column types; imports infer types conservatively. Use project JSON or
XLSX for typed data. XLSX exports text as literal strings, not formulas.

Dataset nodes: GetRows, GetRow, GetField, RowCount, FindRows (matching indices),
SetField, SetRow, AppendRow, DeleteRow, SortDataset, LoadDataset, SaveDataset,
DatasetToDict, DatasetToSet, GetDataset, ForEachRow and GetRowField.
Drag a dataset from the sidebar onto the canvas (or click its adjacent +) to
create a GetDataset node. Connect its Dataset output to dataset operation inputs.
All connections share the same table object; edits preserve object identity.
Existing projects with dataset-name inputs automatically gain GetDataset nodes. SetRow/AppendRow take
a dict containing exactly the dataset's columns. Load/Save choose CSV or XLSX
from the path extension; paths are relative to the project directory. All
function graphs share the current run's datasets. Data reads are evaluated fresh.
Run changes return to the editor, including changes before an error or stop;
**Save** persists them. If you edit data during a run, a button lets you apply
its result explicitly; Undo can restore the earlier data.

Open `dataset-demo.json` from the examples to iterate through two rows, set their
status to `processed`, and print each name.

**Export** downloads a ZIP containing `project.json` (graphs and datasets) and
referenced texture assets. Import the ZIP in another AutoFlow editor, or extract
it and run its project.json using AutoFlow. The ZIP requires AutoFlow; the bundled
runtime remains in the app distribution. Literal texture paths and `assets/`
references, including those inside datasets, are bundled. Runtime-generated paths
and external files read by file-loading nodes are not automatically included;
import those tables into the project first. Missing referenced assets cause an
export error. JSON import remains supported. Save still sets the startup project.

Dataset JSON example:
```json
"datasets": {
  "Data": {
    "columns": ["name", "status"],
    "rows": [{"name": "Ada", "status": "pending"}]
  }
}
```


### Python datatypes

Pin types are `bool`, `integer` (Python `int`), `float`, `string` (Python `str`),
`bytes`, `set`, `dict`, and `reference:Type` (for example `reference:Point`,
`reference:tuple`, or `reference:list`). A plain `reference` pin carries any
Python value and is checked at the receiving typed pin. Optional graph outputs
use `?`; datasets do not have a null datatype. Existing type names are upgraded
when projects load. Integer inputs reject bool and fractional values; float
inputs accept integers and floats.

The Values and Conversions categories provide constructors and explicit
conversions. Float arithmetic is available alongside integer arithmetic.
Sets contain unique hashable values. ForEach accepts lists, tuples, sets and
dicts (dict iteration yields keys; set iteration has no guaranteed order).

Datasets support only bool, integer, float, string and bytes. Types are stored
per column in `types`. Empty or ambiguous columns default to string; mixed
integer/float columns infer float. Leading-zero strings such as `001` stay
strings. Missing cells normalize to the column default (`False`, `0`, `0.0`,
`""`, or empty bytes). Set/dict/tuple/custom-object cells are rejected.
`DatasetToDict` produces `{row_index: row_dict}`; `DatasetToSet` produces unique
row tuples in column order.

Project JSON, ZIP bundles and the editor API preserve bytes, sets, tuples and
Points using tagged JSON values (`$type` and `value`). Bytes use base64; the bytes
editor also accepts plain UTF-8 text. Set and tuple editors accept JSON lists.
CSV/XLSX encode bytes using a `base64:bytes::` prefix and escape strings with
reserved prefixes. Project JSON preserves exact column declarations; CSV/XLSX
imports infer them again. Arbitrary custom Python objects can pass between
nodes by reference during a run; persisting additional custom classes requires
an explicit serialization implementation (no dynamic class loading or pickle).


### Loop nodes

- **For Loop** follows Python `range(start, stop, step)`: Stop is exclusive;
  negative steps are supported and zero step is rejected.
- **Repeat** runs Count times with zero-based Index. Zero performs no iterations.
- **ForEach** iterates a snapshot of a list, tuple, set or dict keys.
- **While Loop** reevaluates Condition before every iteration. Connect a changing
  bool producer; a literal True runs until Break or the iteration limit.
- **For Each Row** takes a Dataset object and exposes Row (dict), Index and Count.
  Connect Row to **Get Row Field** to read a column, or use Dataset + Index with
  SetField to edit the source. Iteration snapshots the initial rows, so appends
  are visited on the next run. Sorting/deleting can invalidate original indices.
- **Break** exits the nearest active loop; **Continue** skips its remaining body.
  Use **If** to branch conditionally. Nested loops handle their own control.

Connect execution to the loop's input, work to Body, and subsequent steps to
Completed. Row/Item/Index are available inside Body and become None after the
loop. Count is the snapshot/range size (or iterations begun for While Loop).
Loops check cancellation and consume the run's step budget even with an empty
body. While Loop also has a configurable iteration limit; exceeding it fails
explicitly. Function calls have their own loop scope.


### Copy/paste and comment boxes

Shift-click nodes to select several, or use Ctrl+A on the canvas. Ctrl+C / Ctrl+V
(or the Copy/Paste buttons) duplicate the selection. Internal data and execution
connections are remapped to the new IDs; connections outside the copied group
are cleared. Clipboard JSON can be pasted into another graph or project when
its called functions/parameters exist. The editor keeps an in-memory fallback
when browser clipboard access is unavailable. Node selection can be moved or
deleted together, and edits support Undo/Redo.

Press C or click Comment to enclose the selected nodes in a Blueprint-style
comment box. Edit its text/color, drag Move to reposition it, and drag Resize
at the lower-right corner to resize it. The checkbox controls movement of
nodes inside the box. Comment boxes and function descriptions are saved with
the graph and do not affect execution.

### String nodes

The Strings category contains Append, Left, Right, Contains, Length, Substring,
Replace, Split, Join, StartsWith, EndsWith, Find, Trim, Upper and Lower. Contains
has a case-sensitive toggle. Length counts Unicode code points; Left/Right and
Substring reject negative lengths. Substring uses a zero-based start (negative
starts count from the end). Find returns -1 for a missing match. Split requires
a nonempty separator; Join takes a list of strings.


### Screen-search performance

FindOnScreen, IfOnScreen, IsOnScreen and FindPointOnScreen share the accelerated
matcher. A full-resolution single-channel squared-error bound rejects impossible
positions, then remaining regions use the original RGB SQDIFF calculation.
The best RGB match is still selected globally. Images are not downscaled,
confidence still means `1 - RGB RMS error / 255`, transparent pixels are ignored,
and every read captures a fresh frame. Physical coordinates and multi-monitor
origins are unchanged.

Small searches, flat or broad matches, nearly tied candidates, and confidence
boundary cases fall back to the original full RGB search. Such cases may have
little speedup (or some filtering overhead). Prepared templates use a 32-entry,
64 MiB LRU cache (one oversized template may exceed the budget), invalidated by
file modification time and size. Switching between textures no longer evicts
all the others. Screenshots and previous match results are never cached.

Run `runtime/python/python.exe scripts/benchmark_screen.py` for synthetic
1080p/4K comparisons. Add `--live` to compare on a desktop frame and saved
textures; it does not click or save screenshots. Benchmarks report matching time
separately from capture time and verify result parity. The original matcher
remains available through `match_image(..., accelerated=False)` or
`WindowsScreen(..., accelerated=False)` for diagnostics.
