from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_opencode_go_key_enabled = fields.Boolean(
        string="Use Opencode Go",
        compute='_compute_ai_opencode_go_key_enabled',
        readonly=False,
        groups='base.group_system',
    )
    ai_opencode_go_api_key = fields.Char(
        string="Opencode Go API Key",
        config_parameter='ai_provider_opencode.api_key',
    )
    ai_opencode_go_base_url = fields.Char(
        string="Opencode Go Base URL",
        config_parameter='ai_provider_opencode.base_url',
        default='https://opencode.ai/zen/go/v1',
    )
    ai_opencode_go_model = fields.Selection(
        selection=[
            ("deepseek-v4-flash", "DeepSeek V4 Flash"),
            ("deepseek-v4-pro", "DeepSeek V4 Pro"),
            ("kimi-k2.7-code", "Kimi K2.7 Code"),
            ("kimi-k2.6", "Kimi K2.6"),
            ("glm-5.2", "GLM-5.2"),
            ("glm-5.1", "GLM-5.1"),
            ("mimo-v2.5", "MiMo-V2.5"),
            ("mimo-v2.5-pro", "MiMo-V2.5 Pro"),
            ("minimax-m3", "MiniMax M3"),
            ("minimax-m2.7", "MiniMax M2.7"),
            ("qwen3.7-max", "Qwen3.7 Max"),
            ("qwen3.7-plus", "Qwen3.7 Plus"),
            ("qwen3.6-plus", "Qwen3.6 Plus"),
        ],
        string="Model",
        config_parameter='ai_provider_opencode.model',
        default='deepseek-v4-flash',
    )

    def _compute_ai_opencode_go_key_enabled(self):
        for record in self:
            record.ai_opencode_go_key_enabled = bool(record.ai_opencode_go_api_key)
