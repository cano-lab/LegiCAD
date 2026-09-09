/*
  LegiCAD Regime Script v0.2

  C# script for a Grasshopper "C# Script" component (Maths > Script > C# Script).
  Reads Sudbury R1 zoning constraints from JSON and generates a feasible
  massing envelope with compliance validation.

  Zero external dependencies: constraints JSON is parsed by the embedded
  MiniJson parser below, so there is no Manage Assemblies / Newtonsoft step.

  COMPONENT SETUP — the component's parameter names must match RunScript
  exactly:

  INPUTS:
    SiteBoundary   [Curve]   closed polyline lot boundary (Type hint: Curve)
    JsonPath       [string]  path to sudbury_r1_constraints.json (optional)
    UnitCount      [int]     number of dwelling units (slider 1-4)
    CeilingHeight  [double]  ceiling height in meters (slider 2.4-3.0)
    TargetUnitSize [double]  target area per unit in sqm (slider 60-120)

  OUTPUTS:
    Massing        [Brep]    proposed 3D massing
    Envelope       [Brep]    max envelope (setbacks + max height)
    Compliance     [string]  human-readable compliance report
    IsValid        [bool]    true if all zoning constraints pass
    DebugInfo      [string]  internal calculation log

  v0.2 fixes over v0.1:
    - RunScript now has the signature Grasshopper actually calls
      (ref object outputs instead of unused class fields)
    - building.max_storeys is read from its "value" child (matches the JSON)
    - FootprintArea is computed before Storeys (v0.1 divided by zero)
    - Footprint is derived from the program brief, capped by the lot
      coverage limit, instead of filling the whole setback envelope
*/

using System;
using System.IO;
using System.Text;
using System.Globalization;
using System.Collections.Generic;
using Rhino;
using Rhino.Geometry;

public class Script_Instance : GH_ScriptInstance
{
  private void RunScript(
    Curve SiteBoundary,
    string JsonPath,
    int UnitCount,
    double CeilingHeight,
    double TargetUnitSize,
    ref object Massing,
    ref object Envelope,
    ref object Compliance,
    ref object IsValid,
    ref object DebugInfo)
  {
    // Clamp program inputs
    _unitCount = Math.Max(1, UnitCount);
    _ceilingHeight = CeilingHeight > 0.1 ? CeilingHeight : 2.7;
    _targetUnitSize = TargetUnitSize > 1.0 ? TargetUnitSize : 80.0;

    try
    {
      LoadConstraints(JsonPath);
      ValidateInputs(SiteBoundary);
      CalculateEnvelope(SiteBoundary);
      CalculateMassing();
      ValidateConstraints();
      GenerateComplianceReport();
    }
    catch (Exception ex)
    {
      _compliance = "ERROR: " + ex.Message;
      _isValid = false;
      _debug.AppendLine(ex.StackTrace);
    }

    Massing = _massing;
    Envelope = _envelope;
    Compliance = _compliance;
    IsValid = _isValid;
    DebugInfo = _debug.ToString();
  }

  // ---------------------------------------------------------------
  // Internal state
  // ---------------------------------------------------------------

  private Dictionary<string, object> _constraints;
  private readonly StringBuilder _debug = new StringBuilder();
  private readonly List<string> _violations = new List<string>();
  private readonly List<string> _warnings = new List<string>();

  private Brep _massing;
  private Brep _envelope;
  private string _compliance = "";
  private bool _isValid;

  private int _unitCount;
  private double _ceilingHeight;
  private double _targetUnitSize;

  private double _siteArea;
  private double _envelopeArea;
  private double _footprintArea;
  private double _grossFloorArea;
  private double _fsr;
  private double _height;
  private int _storeys;
  private Curve _envelopeCurve;

  // ---------------------------------------------------------------
  // Pipeline
  // ---------------------------------------------------------------

  private void LoadConstraints(string jsonPath)
  {
    if (!string.IsNullOrEmpty(jsonPath) && File.Exists(jsonPath))
    {
      string jsonText = File.ReadAllText(jsonPath);
      _constraints = (Dictionary<string, object>) MiniJson.Parse(jsonText);
      _debug.AppendLine("Loaded constraints from: " + jsonPath);
    }
    else
    {
      _constraints = (Dictionary<string, object>) MiniJson.Parse(DefaultConstraints);
      _debug.AppendLine("WARNING: JSON file not found. Using embedded defaults.");
    }
  }

  private void ValidateInputs(Curve site)
  {
    if (site == null)
      throw new Exception("SiteBoundary input is null. Connect a closed curve.");
    if (!site.IsClosed)
      throw new Exception("SiteBoundary must be a closed curve (polygon).");

    AreaMassProperties amp = AreaMassProperties.Compute(site);
    _siteArea = amp.Area;
    if (_siteArea < 1.0)
      throw new Exception("Site area is too small or curve is invalid.");

    _debug.AppendLine("Site area: " + _siteArea.ToString("F1") + " sqm");
  }

  private void CalculateEnvelope(Curve site)
  {
    double front = GetNum("setbacks.front.value");
    double rear = GetNum("setbacks.rear.value");
    double side = GetNum("setbacks.side_interior.value");
    double maxHeight = GetNum("building.max_height.value");

    _debug.AppendLine("Setbacks — front: " + front + "m, rear: " + rear + "m, side: " + side + "m");

    // Simplified model: uniform inset by the smallest setback.
    // A real build distinguishes front/rear/side edges (lot orientation).
    double minSetback = Math.Min(front, Math.Min(rear, side));

    Curve[] offsets = site.Offset(
      Plane.WorldXY, -minSetback, 0.01, CurveOffsetCornerStyle.Sharp);

    if (offsets == null || offsets.Length == 0)
      throw new Exception("Setback offset failed — setbacks may be too large for this lot.");

    _envelopeCurve = offsets[0];
    _envelopeArea = AreaMassProperties.Compute(_envelopeCurve).Area;
    _debug.AppendLine("Envelope (uniform " + minSetback + "m inset): "
      + _envelopeArea.ToString("F1") + " sqm");

    // Envelope brep: inset footprint extruded to max permitted height
    Extrusion ext = Extrusion.Create(_envelopeCurve, maxHeight, true);
    if (ext == null)
      throw new Exception("Could not extrude envelope.");
    _envelope = ext.ToBrep();
  }

  private void CalculateMassing()
  {
    int maxStoreys = GetInt("building.max_storeys.value");
    double maxHeight = GetNum("building.max_height.value");
    double maxCoverage = GetNum("building.max_lot_coverage.value");

    // Footprint is limited by the envelope AND the coverage rule
    double maxFootprint = Math.Min(_envelopeArea, maxCoverage * _siteArea);

    // Program brief drives the area we actually need
    double requiredArea = _unitCount * _targetUnitSize;

    // Storeys needed to fit the program on the permitted footprint
    _storeys = (int) Math.Ceiling(requiredArea / maxFootprint);
    _storeys = Math.Max(1, Math.Min(_storeys, maxStoreys));

    _footprintArea = requiredArea / _storeys;
    if (_footprintArea > maxFootprint)
    {
      _footprintArea = maxFootprint;
      _warnings.Add("Program does not fully fit: "
        + (_footprintArea * _storeys).ToString("F0") + " sqm of "
        + requiredArea.ToString("F0") + " sqm requested.");
    }

    _grossFloorArea = _footprintArea * _storeys;
    _fsr = _grossFloorArea / _siteArea;
    _height = _storeys * _ceilingHeight;

    // Scale the envelope curve about its centroid to the required footprint
    Point3d centroid = AreaMassProperties.Compute(_envelopeCurve).Centroid;
    double scale = Math.Sqrt(_footprintArea / _envelopeArea);
    Curve footprint = _envelopeCurve.DuplicateCurve();
    footprint.Transform(Transform.Scale(
      new Plane(centroid, Vector3d.ZAxis), scale, scale, 1.0));

    Extrusion ext = Extrusion.Create(footprint, _height, true);
    if (ext == null)
      throw new Exception("Could not extrude massing.");
    _massing = ext.ToBrep();

    _debug.AppendLine("Storeys: " + _storeys);
    _debug.AppendLine("Footprint: " + _footprintArea.ToString("F1") + " sqm");
    _debug.AppendLine("Gross floor area: " + _grossFloorArea.ToString("F1") + " sqm");
    _debug.AppendLine("FSR: " + _fsr.ToString("F3"));
    _debug.AppendLine("Height: " + _height.ToString("F1") + "m");
  }

  private void ValidateConstraints()
  {
    _violations.Clear();

    double maxHeight = GetNum("building.max_height.value");
    if (_height > maxHeight)
      _violations.Add("Height exceeds maximum: "
        + _height.ToString("F1") + "m > " + maxHeight + "m");

    int maxStoreys = GetInt("building.max_storeys.value");
    if (_storeys > maxStoreys)
      _violations.Add("Storeys exceed maximum: " + _storeys + " > " + maxStoreys);

    double maxFSR = GetNum("building.max_fsr.value");
    if (_fsr > maxFSR)
      _violations.Add("FSR exceeds maximum: "
        + _fsr.ToString("F3") + " > " + maxFSR);

    double maxCoverage = GetNum("building.max_lot_coverage.value");
    double coverage = _footprintArea / _siteArea;
    if (coverage > maxCoverage)
      _violations.Add("Lot coverage exceeds maximum: "
        + coverage.ToString("F3") + " > " + maxCoverage);

    double maxGFA = GetNum("building.max_gross_floor_area.value");
    if (_grossFloorArea > maxGFA)
      _violations.Add("Gross floor area exceeds maximum: "
        + _grossFloorArea.ToString("F0") + " sqm > " + maxGFA + " sqm");

    int maxUnits = GetInt("units.max_units");
    if (_unitCount > maxUnits)
      _violations.Add("Unit count exceeds maximum for zone: "
        + _unitCount + " > " + maxUnits);

    _isValid = _violations.Count == 0;
  }

  private void GenerateComplianceReport()
  {
    StringBuilder sb = new StringBuilder();
    sb.AppendLine("=== LEGICAD COMPLIANCE REPORT ===");
    sb.AppendLine("Zone: " + GetStr("metadata.zone")
      + " — " + GetStr("metadata.jurisdiction"));
    sb.AppendLine();
    sb.AppendLine("--- PROPOSED BUILDING ---");
    sb.AppendLine("Units: " + _unitCount);
    sb.AppendLine("Storeys: " + _storeys);
    sb.AppendLine("Height: " + _height.ToString("F1") + "m");
    sb.AppendLine("Footprint: " + _footprintArea.ToString("F1") + " sqm");
    sb.AppendLine("Gross floor area: " + _grossFloorArea.ToString("F1") + " sqm");
    sb.AppendLine("FSR: " + _fsr.ToString("F3"));
    sb.AppendLine("Lot coverage: " + (_footprintArea / _siteArea).ToString("F3"));
    sb.AppendLine();
    sb.AppendLine("--- CONSTRAINT CHECKS ---");
    sb.AppendLine(CheckLine("Height", _height, GetNum("building.max_height.value"), "F1", "m"));
    sb.AppendLine(CheckLine("FSR", _fsr, GetNum("building.max_fsr.value"), "F3", ""));
    sb.AppendLine(CheckLine("Coverage", _footprintArea / _siteArea,
      GetNum("building.max_lot_coverage.value"), "F3", ""));
    sb.AppendLine(CheckLine("GFA", _grossFloorArea,
      GetNum("building.max_gross_floor_area.value"), "F0", " sqm"));

    if (_warnings.Count > 0)
    {
      sb.AppendLine();
      sb.AppendLine("--- WARNINGS ---");
      foreach (string w in _warnings) sb.AppendLine("  ! " + w);
    }

    sb.AppendLine();
    if (_isValid)
    {
      sb.AppendLine("=== RESULT: COMPLIANT ===");
    }
    else
    {
      sb.AppendLine("=== RESULT: NON-COMPLIANT ===");
      foreach (string v in _violations) sb.AppendLine("  x " + v);
    }

    _compliance = sb.ToString();

    // Tag the massing so a downstream component can color it
    if (_massing != null)
      _massing.UserDictionary.Set("compliant", _isValid);
  }

  private static string CheckLine(string label, double actual, double max, string fmt, string unit)
  {
    return label + ": " + actual.ToString(fmt) + unit
      + " / " + max.ToString(fmt) + unit
      + "  " + (actual <= max ? "PASS" : "FAIL");
  }

  // ---------------------------------------------------------------
  // Constraint accessors (dot-separated path into the JSON tree)
  // ---------------------------------------------------------------

  private object GetNode(string path)
  {
    object node = _constraints;
    foreach (string seg in path.Split('.'))
    {
      Dictionary<string, object> dict = node as Dictionary<string, object>;
      if (dict == null || !dict.TryGetValue(seg, out node))
        throw new Exception("Constraint not found in JSON: " + path);
    }
    return node;
  }

  private double GetNum(string path)
  {
    return Convert.ToDouble(GetNode(path), CultureInfo.InvariantCulture);
  }

  private int GetInt(string path)
  {
    return (int) Math.Round(GetNum(path));
  }

  private string GetStr(string path)
  {
    return Convert.ToString(GetNode(path), CultureInfo.InvariantCulture);
  }

  private const string DefaultConstraints = @"{
  ""metadata"": {
    ""name"": ""Sudbury R1-Residential Single Detached"",
    ""jurisdiction"": ""City of Greater Sudbury"",
    ""zone"": ""R1""
  },
  ""building"": {
    ""max_height"": { ""value"": 10.0 },
    ""max_storeys"": { ""value"": 2 },
    ""max_gross_floor_area"": { ""value"": 300.0 },
    ""max_lot_coverage"": { ""value"": 0.40 },
    ""max_fsr"": { ""value"": 0.50 }
  },
  ""setbacks"": {
    ""front"": { ""value"": 6.0 },
    ""rear"": { ""value"": 7.5 },
    ""side_interior"": { ""value"": 1.2 }
  },
  ""units"": { ""max_units"": 1 }
}";

  // ---------------------------------------------------------------
  // MiniJson — minimal dependency-free JSON parser.
  // Produces Dictionary<string,object> / List<object> / string /
  // double / bool / null. Supports objects, arrays, strings with
  // escapes, numbers, and the three literals.
  // ---------------------------------------------------------------

  public static class MiniJson
  {
    public static object Parse(string json)
    {
      int i = 0;
      object value = ParseValue(json, ref i);
      return value;
    }

    private static void SkipWs(string s, ref int i)
    {
      while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
    }

    private static object ParseValue(string s, ref int i)
    {
      SkipWs(s, ref i);
      if (i >= s.Length) throw new Exception("Unexpected end of JSON");
      char c = s[i];
      if (c == '{') return ParseObject(s, ref i);
      if (c == '[') return ParseArray(s, ref i);
      if (c == '"') return ParseString(s, ref i);
      if (c == 't') { Expect(s, ref i, "true"); return true; }
      if (c == 'f') { Expect(s, ref i, "false"); return false; }
      if (c == 'n') { Expect(s, ref i, "null"); return null; }
      return ParseNumber(s, ref i);
    }

    private static void Expect(string s, ref int i, string literal)
    {
      if (string.Compare(s, i, literal, 0, literal.Length) != 0)
        throw new Exception("Invalid JSON literal at index " + i);
      i += literal.Length;
    }

    private static Dictionary<string, object> ParseObject(string s, ref int i)
    {
      var dict = new Dictionary<string, object>();
      i++; // consume '{'
      SkipWs(s, ref i);
      if (i < s.Length && s[i] == '}')
      {
        i++;
        return dict;
      }
      while (true)
      {
        SkipWs(s, ref i);
        string key = ParseString(s, ref i);
        SkipWs(s, ref i);
        if (i >= s.Length || s[i] != ':')
          throw new Exception("Expected ':' in JSON object at index " + i);
        i++;
        dict[key] = ParseValue(s, ref i);
        SkipWs(s, ref i);
        if (i >= s.Length) throw new Exception("Unterminated JSON object");
        if (s[i] == ',') { i++; continue; }
        if (s[i] == '}') { i++; return dict; }
        throw new Exception("Expected ',' or '}' in JSON object at index " + i);
      }
    }

    private static List<object> ParseArray(string s, ref int i)
    {
      var list = new List<object>();
      i++; // consume '['
      SkipWs(s, ref i);
      if (i < s.Length && s[i] == ']')
      {
        i++;
        return list;
      }
      while (true)
      {
        list.Add(ParseValue(s, ref i));
        SkipWs(s, ref i);
        if (i >= s.Length) throw new Exception("Unterminated JSON array");
        if (s[i] == ',') { i++; continue; }
        if (s[i] == ']') { i++; return list; }
        throw new Exception("Expected ',' or ']' in JSON array at index " + i);
      }
    }

    private static string ParseString(string s, ref int i)
    {
      if (i >= s.Length || s[i] != '"')
        throw new Exception("Expected string at index " + i);
      i++; // consume opening quote
      var sb = new StringBuilder();
      while (i < s.Length)
      {
        char c = s[i++];
        if (c == '"') return sb.ToString();
        if (c == '\\')
        {
          if (i >= s.Length) break;
          char esc = s[i++];
          switch (esc)
          {
            case '"': sb.Append('"'); break;
            case '\\': sb.Append('\\'); break;
            case '/': sb.Append('/'); break;
            case 'b': sb.Append('\b'); break;
            case 'f': sb.Append('\f'); break;
            case 'n': sb.Append('\n'); break;
            case 'r': sb.Append('\r'); break;
            case 't': sb.Append('\t'); break;
            case 'u':
              if (i + 4 > s.Length) throw new Exception("Bad \\u escape in JSON");
              sb.Append((char) int.Parse(s.Substring(i, 4),
                NumberStyles.HexNumber, CultureInfo.InvariantCulture));
              i += 4;
              break;
            default:
              throw new Exception("Bad escape '\\" + esc + "' in JSON string");
          }
        }
        else
        {
          sb.Append(c);
        }
      }
      throw new Exception("Unterminated JSON string");
    }

    private static double ParseNumber(string s, ref int i)
    {
      int start = i;
      if (i < s.Length && s[i] == '-') i++;
      while (i < s.Length && char.IsDigit(s[i])) i++;
      if (i < s.Length && s[i] == '.')
      {
        i++;
        while (i < s.Length && char.IsDigit(s[i])) i++;
      }
      if (i < s.Length && (s[i] == 'e' || s[i] == 'E'))
      {
        i++;
        if (i < s.Length && (s[i] == '+' || s[i] == '-')) i++;
        while (i < s.Length && char.IsDigit(s[i])) i++;
      }
      string token = s.Substring(start, i - start);
      return double.Parse(token, NumberStyles.Float, CultureInfo.InvariantCulture);
    }
  }
}
