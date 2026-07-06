import { Composer } from "@mail/core/common/composer";
import { toRaw } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";

patch(Composer.prototype, {
    onFocusin(ev) {
        ev.stopPropagation();
        const composer = toRaw(this.props.composer);
        composer.isFocused = true;
        if (
            composer.thread?.scrollTop === "bottom" &&
            !composer.thread.scrollUnread &&
            !composer.thread.markedAsUnread
        ) {
            composer.thread?.markAsRead();
        }
        if (this.thread?.channel_type === "ai_chat") {
            ev.target.select();
        }
    },
});
