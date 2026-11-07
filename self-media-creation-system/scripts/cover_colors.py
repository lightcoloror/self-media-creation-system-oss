"""Explicit per-content/per-account color decisions, not an aesthetic classifier.

No universal palette. Local layouts can be checked against the selected colors;
photograph/native-generation pixels still require actual visual review.
"""
import copy
import re


def starter():
    return dict(mode='content', account='', palette={}, content_basis=[], rationale='')


def validate(selection, account=None):
    if not isinstance(selection, dict) or selection.get('mode') not in ('content', 'brand'):
        raise ValueError('color_selection_mode_required')
    if not isinstance(selection.get('account'), str) or not selection['account'].strip():
        raise ValueError('color_selection_account_required')
    if account is not None and selection['account'] != account:
        raise ValueError('color_selection_account_mismatch')
    if not isinstance(selection.get('rationale'), str) or not selection['rationale'].strip():
        raise ValueError('color_selection_rationale_required')
    basis = selection.get('content_basis')
    if not isinstance(basis, list) or not basis or any(not isinstance(v, str) or not v.strip() for v in basis):
        raise ValueError('color_selection_content_basis_required')
    palette = selection.get('palette')
    if not isinstance(palette, dict) or not all(k in palette for k in ('background', 'foreground', 'accent')):
        raise ValueError('color_selection_palette_required')
    if any(not isinstance(v, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', v) for v in palette.values()):
        raise ValueError('color_selection_invalid_color')
    if selection['mode'] == 'brand':
        # Explicit project applicability, never infer it from account/title keywords.
        if selection.get('brand_applies_to_content') is not True or not selection.get('brand_ref'):
            raise ValueError('brand_color_scope_and_reference_required')
        import cover_workbench as w
        w.bound(selection['brand_ref'])
    return selection


def resolve(master, candidate):
    if 'color_selection' in candidate or 'color_selection' in master:
        choice = copy.deepcopy(candidate.get('color_selection', master.get('color_selection')))
        validate(choice, master['account'])
        return choice['palette'], choice
    # Historical explicit palettes remain replayable, without claiming that a
    # content-driven choice was made. New design-init never supplies this default.
    palette = master.get('palette')
    if not isinstance(palette, dict) or not all(k in palette for k in ('background', 'foreground', 'accent')):
        raise ValueError('color_selection_required_no_universal_palette')
    return palette, None


def validate_plan(plan, selection):
    validate(selection, plan.get('brand', {}).get('account'))
    if plan.get('color_selection') != selection:
        raise ValueError('color_selection_plan_drift')
    if plan.get('brand', {}).get('palette') != selection['palette']:
        raise ValueError('color_selection_palette_drift')
    allowed = {v.upper() for v in selection['palette'].values()}
    layouts = plan.get('render_spec', {}).get('profile_layouts', {})
    if not layouts:
        raise ValueError('color_selection_requires_editable_layouts')
    for layout in layouts.values():
        scene = layout.get('cover_layers', {})
        if not scene or scene.get('background', '').upper() != selection['palette']['background'].upper():
            raise ValueError('color_selection_background_drift')
        for layer in scene.get('layers', []):
            if layer.get('type') != 'image' and layer.get('color', '').upper() not in allowed:
                raise ValueError('color_selection_layer_drift: ' + str(layer.get('id')))
