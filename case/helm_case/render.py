"""Offscreen preview renders with VTK (installed alongside CadQuery)."""

import math

import vtk

from . import params as P


def _polydata(shape, tol=0.05):
    verts, tris = shape.tessellate(tol, 0.2)
    pts = vtk.vtkPoints()
    for v in verts:
        pts.InsertNextPoint(v.x, v.y, v.z)
    cells = vtk.vtkCellArray()
    for a, b, c in tris:
        cells.InsertNextCell(3)
        cells.InsertCellPoint(a)
        cells.InsertCellPoint(b)
        cells.InsertCellPoint(c)
    poly = vtk.vtkPolyData()
    poly.SetPoints(pts)
    poly.SetPolys(cells)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(poly)
    normals.SetFeatureAngle(35)
    normals.SplittingOn()
    normals.Update()
    return normals.GetOutput()


def render(items, filename, azimuth=-35.0, elevation=28.0, size=(1600, 1100), zoom=1.0, skip=()):
    ren = vtk.vtkRenderer()
    ren.SetBackground(0.93, 0.93, 0.94)
    ren.SetBackground2(0.78, 0.79, 0.82)
    ren.GradientBackgroundOn()
    for it in items:
        if it.name in skip or any(it.name.startswith(s) for s in skip):
            continue
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(_polydata(it.shape))
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*it.color)
        prop.SetAmbient(0.25)
        prop.SetDiffuse(0.75)
        prop.SetSpecular(0.25)
        prop.SetSpecularPower(30)
        if it.name in ("light_holder", "screen"):
            prop.SetAmbient(0.8)
        ren.AddActor(actor)

    kit = vtk.vtkLightKit()
    kit.SetKeyLightIntensity(0.9)
    kit.AddLightsToRenderer(ren)

    cx, cy, cz = P.WIDTH / 2, P.DEPTH / 2, P.BACK_HEIGHT / 2
    cam = ren.GetActiveCamera()
    cam.SetFocalPoint(cx, cy, cz)
    dist = 520.0
    az, el = math.radians(azimuth), math.radians(elevation)
    cam.SetPosition(cx + dist * math.sin(az) * math.cos(el), cy - dist * math.cos(az) * math.cos(el), cz + dist * math.sin(el))
    cam.SetViewUp(0, 0, 1)
    cam.SetViewAngle(30)
    ren.ResetCameraClippingRange()
    cam.Zoom(zoom)
    ren.UseFXAAOn()

    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.AddRenderer(ren)
    win.SetSize(*size)
    win.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(filename))
    writer.SetInputConnection(grab.GetOutputPort())
    writer.Write()
