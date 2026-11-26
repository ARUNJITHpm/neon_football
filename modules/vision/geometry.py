"""Image-space opening checks and conservative goal-frame sphere bounds."""


def inside_polygon(point, polygon):
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        cross = (b[0]-a[0])*(y-a[1]) - (b[1]-a[1])*(x-a[0])
        if abs(cross) < 1e-8 and min(a[0], b[0]) <= x <= max(a[0], b[0]) and min(a[1], b[1]) <= y <= max(a[1], b[1]):
            return True
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return inside


def box_overlap(box, polygon):
    if len(polygon) < 3:
        return False
    xs, ys = zip(*polygon)
    return box[0] <= max(xs) and box[2] >= min(xs) and box[1] <= max(ys) and box[3] >= min(ys)


def opening_contains(position, view):
    radius = view.ball_radius_m + view.plane_margin_m
    ux, uy, uz = position.uncertainty_m
    return (position.x_m-radius-ux >= 0 and position.x_m+radius+ux <= view.opening_width_m and
            position.y_m-radius-uy >= 0 and position.y_m+radius+uy <= view.opening_height_m)


def opening_possible(position, view):
    """Reject intervals entirely outside the opening, even for review candidates."""
    radius = view.ball_radius_m + view.plane_margin_m
    ux, uy, _ = position.uncertainty_m
    return (position.x_m+radius+ux >= 0 and position.x_m-radius-ux <= view.opening_width_m and
            position.y_m+radius+uy >= 0 and position.y_m-radius-uy <= view.opening_height_m)


def valid_calibration(view, width, height):
    calibration = view.calibration
    errors = []
    if calibration.status != "measured":
        errors.append("calibration_not_measured")
    if (width, height) != (calibration.width, calibration.height):
        errors.append("resolution_mismatch")
    if not calibration.goal_roi:
        errors.append("goal_roi_missing")
    if calibration.reprojection_error_px is None or calibration.reprojection_error_px > view.max_reprojection_error_px:
        errors.append("reprojection_error_exceeds_budget")
    return errors
