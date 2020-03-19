# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'NAI Game',
    'category': 'Analytics',
    'summary': 'NAI Game Analytics',
    'version': '0.1',
    'description': """
NAI Game Analytics
""",
    'depends': ['base','mail'],
    'data': [
        'ir.model.access.csv',
        'nai_game_view.xml',
    ],
    'installable': True,
    'auto_install': False,
}
