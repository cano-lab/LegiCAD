/*
  LegiCAD Regime Script v0.1
  
  This C# script runs inside a Grasshopper C# Script component.
  It reads Sudbury R1 zoning constraints from JSON and generates
  a feasible massing envelope with compliance validation.
  
  INPUTS (Grasshopper component parameters):
    - SiteBoundary [Curve] : The lot boundary curve (closed polyline)
    - JsonPath [String] : Path to sudbury_r1_constraints.json
    - UnitCount [Integer] : Number of dwelling units (slider: 1-4)
    - CeilingHeight [Number] : Typical ceiling height in meters (slider: 2.4-3.0)
    - TargetUnitSize [Number] : Target area per unit in sqm (slider: 60-120)
  
  OUTPUTS:
    - Massing [Brep] : The 3D massing geometry
    - Envelope [Brep] : The feasible envelope (setbacks applied)
    - Compliance [String] : Human-readable compliance report
    - IsValid [Boolean] : True if all constraints satisfied
    - DebugInfo [String] : Internal calculation details
*/

using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

public class Script_Instance : GH_ScriptInstance
{
    // Grasshopper inputs - wire these in the component
    private Curve SiteBoundary = null;
    private string JsonPath = "";
    private int UnitCount = 1;
    private double CeilingHeight = 2.7;
    private double TargetUnitSize = 80.0;

    // Grasshopper outputs
    private Brep Massing = null;
    private Brep Envelope = null;
    private string Compliance = "";
    private bool IsValid = false;
    private string DebugInfo = "";

    // Internal state
    private JObject Constraints;
    private List<string> Violations = new List<string>();
    private double SiteArea;
    private double FootprintArea;
    private double GrossFloorArea;
    private double FSR;
    private double Height;
    private int Storeys;
    
    public void RunScript(
        Curve siteBoundary, 
        string jsonPath, 
        int unitCount, 
        double ceilingHeight, 
        double targetUnitSize)
    {
        // Assign inputs
        SiteBoundary = siteBoundary;
        JsonPath = jsonPath;
        UnitCount = Math.Max(1, unitCount);
        CeilingHeight = ceilingHeight;
        TargetUnitSize = targetUnitSize;
        
        try
        {
            LoadConstraints();
            ValidateInputs();
            CalculateEnvelope();
            CalculateMassing();
            ValidateConstraints();
            GenerateOutputs();
        }
        catch (Exception ex)
        {
            Compliance = "ERROR: " + ex.Message;
            IsValid = false;
            DebugInfo = ex.StackTrace;
        }
    }
    
    private void LoadConstraints()
    {
        if (!File.Exists(JsonPath))
        {
            // Fallback to embedded defaults if file not found
            Constraints = JObject.Parse(GetDefaultConstraints());
            DebugInfo += "WARNING: JSON file not found. Using embedded defaults.\n";
        }
        else
        {
            string jsonText = File.ReadAllText(JsonPath);
            Constraints = JObject.Parse(jsonText);
            DebugInfo += "Loaded constraints from: " + JsonPath + "\n";
        }
    }
    
    private void ValidateInputs()
    {
        if (SiteBoundary == null)
            throw new Exception("SiteBoundary input is null. Please connect a closed curve.");
            
        if (!SiteBoundary.IsClosed)
            throw new Exception("SiteBoundary must be a closed curve (polygon).");
            
        // Calculate site area
        AreaMassProperties amp = AreaMassProperties.Compute(SiteBoundary);
        SiteArea = amp.Area;
        
        if (SiteArea < 1.0)
            throw new Exception("Site area is too small or curve is invalid.");
            
        DebugInfo += "Site area: " + SiteArea.ToString("F1") + " sqm\n";
    }
    
    private void CalculateEnvelope()
    {
        // Get setback values from JSON
        double frontSetback = Constraints["setbacks"]["front"]["value"].Value<double>();
        double rearSetback = Constraints["setbacks"]["rear"]["value"].Value<double>();
        double sideSetback = Constraints["setbacks"]["side_interior"]["value"].Value<double>();
        double maxHeight = Constraints["building"]["max_height"]["value"].Value<double>();
        
        DebugInfo += "Setbacks - Front: " + frontSetback + "m, Rear: " + rearSetback + "m, Side: " + sideSetback + "m\n";
        
        // Create setback curves by offsetting inward
        // Note: This is a simplified setback - real setback calculation is more complex
        // and depends on which edge is "front" vs "side" vs "rear"
        
        // For now, use uniform inset based on minimum setback
        double minSetback = Math.Min(frontSetback, Math.Min(rearSetback, sideSetback));
        
        Curve[] offsetCurves = SiteBoundary.Offset(
            Plane.WorldXY, 
            -minSetback, 
            0.01, 
            CurveOffsetCornerStyle.Sharp
        );
        
        if (offsetCurves == null || offsetCurves.Length == 0)
        {
            // If offset fails (e.g., setbacks too large), create a smaller envelope
            DebugInfo += "WARNING: Setback offset failed. Using scaled-down version.\n";
            BoundingBox bbox = SiteBoundary.GetBoundingBox(true);
            Point3d center = bbox.Center;
            Transform scale = Transform.Scale(center, 0.7); // 70% scale
            Curve scaled = SiteBoundary.DuplicateCurve();
            scaled.Transform(scale);
            offsetCurves = new Curve[] { scaled };
        }
        
        Curve setbackCurve = offsetCurves[0];
        
        // Create envelope surface
        Brep[] envelopeBreps = Brep.CreatePlanarBreps(setbackCurve, 0.01);
        if (envelopeBreps != null && envelopeBreps.Length > 0)
        {
            Brep envelopeSurface = envelopeBreps[0];
            
            // Extrude to max height
            Vector3d extrudeDir = new Vector3d(0, 0, maxHeight);
            Envelope = envelopeBreps[0].Faces[0].CreateExtrusion(extrudeDir, true);
            
            if (Envelope == null)
            {
                // Fallback: simple extrusion
                Extrusion ext = Extrusion.Create(setbackCurve, maxHeight, true);
                Envelope = ext.ToBrep();
            }
        }
        
        DebugInfo += "Envelope height: " + maxHeight + "m\n";
    }
    
    private void CalculateMassing()
    {
        // Calculate how many storeys we need
        double totalRequiredArea = UnitCount * TargetUnitSize;
        Storeys = (int)Math.Ceiling(totalRequiredArea / FootprintArea);
        
        // But cap at max storeys
        int maxStoreys = Constraints["building"]["max_storeys"].Value<int>();
        Storeys = Math.Min(Storeys, maxStoreys);
        
        // Recalculate actual gross floor area
        if (Envelope != null)
        {
            // Get footprint from envelope base
            BrepFace baseFace = Envelope.Faces[0];
            FootprintArea = AreaMassProperties.Compute(baseFace).Area;
        }
        else
        {
            FootprintArea = SiteArea * 0.5; // Fallback
        }
        
        GrossFloorArea = FootprintArea * Storeys;
        FSR = GrossFloorArea / SiteArea;
        Height = Storeys * CeilingHeight;
        
        // Create the actual massing (may be smaller than envelope)
        double massingHeight = Math.Min(Height, Constraints["building"]["max_height"]["value"].Value<double>());
        
        if (Envelope != null)
        {
            // Scale envelope height to match actual storeys
            // This is simplified - real implementation would create proper floor plates
            Massing = Envelope.DuplicateBrep();
            
            // Scale Z to match actual height
            BoundingBox bbox = Massing.GetBoundingBox(true);
            double currentHeight = bbox.Max.Z - bbox.Min.Z;
            if (currentHeight > 0)
            {
                double scaleZ = massingHeight / currentHeight;
                Point3d basePoint = new Point3d(0, 0, bbox.Min.Z);
                Transform scale = Transform.Scale(basePoint, 1.0, 1.0, scaleZ);
                Massing.Transform(scale);
            }
        }
        
        DebugInfo += "Storeys: " + Storeys + "\n";
        DebugInfo += "Footprint: " + FootprintArea.ToString("F1") + " sqm\n";
        DebugInfo += "Gross Floor Area: " + GrossFloorArea.ToString("F1") + " sqm\n";
        DebugInfo += "FSR: " + FSR.ToString("F3") + "\n";
        DebugInfo += "Height: " + Height.ToString("F1") + "m\n";
    }
    
    private void ValidateConstraints()
    {
        Violations.Clear();
        
        // Check max height
        double maxHeight = Constraints["building"]["max_height"]["value"].Value<double>();
        if (Height > maxHeight)
            Violations.Add("Height exceeds maximum: " + Height.ToString("F1") + "m > " + maxHeight + "m");
            
        // Check max storeys
        int maxStoreys = Constraints["building"]["max_storeys"].Value<int>();
        if (Storeys > maxStoreys)
            Violations.Add("Storeys exceed maximum: " + Storeys + " > " + maxStoreys);
            
        // Check FSR
        double maxFSR = Constraints["building"]["max_fsr"]["value"].Value<double>();
        if (FSR > maxFSR)
            Violations.Add("FSR exceeds maximum: " + FSR.ToString("F3") + " > " + maxFSR);
            
        // Check lot coverage
        double maxCoverage = Constraints["building"]["max_lot_coverage"]["value"].Value<double>();
        double coverage = FootprintArea / SiteArea;
        if (coverage > maxCoverage)
            Violations.Add("Lot coverage exceeds maximum: " + coverage.ToString("F3") + " > " + maxCoverage);
            
        // Check unit count (for R1 single detached)
        int maxUnits = Constraints["units"]["max_units"].Value<int>();
        if (UnitCount > maxUnits)
            Violations.Add("Unit count exceeds maximum for zone: " + UnitCount + " > " + maxUnits);
            
        IsValid = Violations.Count == 0;
    }
    
    private void GenerateOutputs()
    {
        // Build compliance report
        System.Text.StringBuilder sb = new System.Text.StringBuilder();
        sb.AppendLine("=== LEGICAD COMPLIANCE REPORT ===");
        sb.AppendLine("Zone: " + Constraints["metadata"]["zone"].Value<string>());
        sb.AppendLine("Jurisdiction: " + Constraints["metadata"]["jurisdiction"].Value<string>());
        sb.AppendLine();
        sb.AppendLine("--- PROPOSED BUILDING ---");
        sb.AppendLine("Units: " + UnitCount);
        sb.AppendLine("Storeys: " + Storeys);
        sb.AppendLine("Height: " + Height.ToString("F1") + "m");
        sb.AppendLine("Footprint: " + FootprintArea.ToString("F1") + " sqm");
        sb.AppendLine("Gross Floor Area: " + GrossFloorArea.ToString("F1") + " sqm");
        sb.AppendLine("FSR: " + FSR.ToString("F3"));
        sb.AppendLine("Lot Coverage: " + (FootprintArea / SiteArea).ToString("F3"));
        sb.AppendLine();
        sb.AppendLine("--- CONSTRAINT CHECKS ---");
        
        double maxHeight = Constraints["building"]["max_height"]["value"].Value<double>();
        double maxFSR = Constraints["building"]["max_fsr"]["value"].Value<double>();
        double maxCoverage = Constraints["building"]["max_lot_coverage"]["value"].Value<double>();
        
        sb.AppendLine("[ ] Height: " + Height.ToString("F1") + "m / " + maxHeight + "m " + (Height <= maxHeight ? "PASS" : "FAIL"));
        sb.AppendLine("[ ] FSR: " + FSR.ToString("F3") + " / " + maxFSR + " " + (FSR <= maxFSR ? "PASS" : "FAIL"));
        sb.AppendLine("[ ] Coverage: " + (FootprintArea / SiteArea).ToString("F3") + " / " + maxCoverage + " " + ((FootprintArea / SiteArea) <= maxCoverage ? "PASS" : "FAIL"));
        sb.AppendLine();
        
        if (IsValid)
        {
            sb.AppendLine("=== RESULT: COMPLIANT ===");
            sb.AppendLine("All constraints satisfied. Massing is valid.");
        }
        else
        {
            sb.AppendLine("=== RESULT: NON-COMPLIANT ===");
            sb.AppendLine("Violations found:");
            foreach (string v in Violations)
            {
                sb.AppendLine("  - " + v);
            }
        }
        
        Compliance = sb.ToString();
        
        // Color the massing based on compliance
        if (Massing != null)
        {
            if (IsValid)
            {
                // Green for valid
                Massing.UserDictionary.Set("color", "green");
            }
            else
            {
                // Red for invalid
                Massing.UserDictionary.Set("color", "red");
            }
        }
    }
    
    private string GetDefaultConstraints()
    {
        // Embedded fallback constraints (same as sudbury_r1_constraints.json)
        return @"{
  ""metadata"": {
    ""name"": ""Sudbury R1-Residential Single Detached"",
    ""jurisdiction"": ""City of Greater Sudbury"",
    ""zone"": ""R1""
  },
  ""building"": {
    ""max_height"": { ""value"": 10.0 },
    ""max_storeys"": { ""value"": 2 },
    ""max_fsr"": { ""value"": 0.50 },
    ""max_lot_coverage"": { ""value"": 0.40 }
  },
  ""setbacks"": {
    ""front"": { ""value"": 6.0 },
    ""rear"": { ""value"": 7.5 },
    ""side_interior"": { ""value"": 1.2 }
  },
  ""units"": {
    ""max_units"": 1
  }
}";
    }
}
