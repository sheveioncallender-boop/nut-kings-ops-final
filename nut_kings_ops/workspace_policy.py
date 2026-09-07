"""Workspace selection only; stock operation codes and workflows stay unchanged."""

WORKSPACES = {
    'raw-materials/receiving': {
        'label': 'Raw Materials — Receiving', 'team': 'Office',
        'role': 'office_receiving', 'page': 'raw', 'operations': ('raw_receipt',),
    },
    'raw-materials/issuing': {
        'label': 'Raw Materials — Issuing', 'team': 'Employee',
        'role': 'raw_material_issue', 'page': 'raw', 'operations': ('raw_issue',),
    },
    'finished-goods/receiving': {
        'label': 'Finished Goods — Receiving', 'team': 'Employee',
        'role': 'finished_goods_entry', 'page': 'finished', 'operations': ('finished_receipt',),
    },
    'finished-goods/issued': {
        'label': 'Finished Goods — Issued', 'team': 'Office',
        'role': 'dispatcher', 'page': 'finished',
        'operations': ('finished_to_truck', 'customer_delivery', 'truck_return'),
    },
}


def workspace_allowed(permissions, entry):
    if entry == 'admin':
        return bool(permissions.get('system'))
    definition = WORKSPACES.get(entry)
    return bool(definition and permissions.get(definition['role']))


def scoped_permissions(permissions, entry):
    if not entry:
        return dict(permissions)
    if not workspace_allowed(permissions, entry):
        raise PermissionError('This account is not assigned to the selected workspace.')
    if entry == 'admin':
        return dict(permissions)
    definition = WORKSPACES[entry]
    capabilities = [op for op in definition['operations'] if op in permissions['capabilities']]
    result = {key: False for key, value in permissions.items() if isinstance(value, bool)}
    result.update({
        definition['role']: True,
        definition['page']: True,
        'system': bool(permissions.get('system')),
        'capabilities': capabilities,
        'has_nutkings_access': bool(capabilities),
        # Retain the original dispatch workflow; van development is deferred.
        'distribution': definition['role'] == 'dispatcher',
        'contacts': definition['role'] == 'dispatcher',
    })
    return result
