from odoo import fields, models


class AiAvailableModel(models.Model):
    _name = 'ai.available.model'
    _description = 'AI Available Model'
    _rec_name = 'name'
    _order = 'sequence, name'

    provider = fields.Selection(
        selection=[
            ('opencode_go', 'Opencode Go'),
        ],
        required=True,
        index=True,
    )
    model_id = fields.Char(
        string="Model ID",
        required=True,
        help="The API identifier used when calling the provider.",
    )
    name = fields.Char(string="Model Name", required=True)
    is_default = fields.Boolean(
        default=False,
        help="Default models are seeded on install.",
    )
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        ('unique_provider_model', 'UNIQUE(provider, model_id)',
         'A model with this ID already exists for this provider.'),
    ]
