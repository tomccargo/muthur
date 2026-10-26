// System / Dark / Light (DESIGN.md §5). The choice is remembered when storage allows it.
import { useState } from 'react';
const KEY = 'muthur.theme';
function read() {
    try {
        const v = localStorage.getItem(KEY);
        return v === 'dark' || v === 'light' ? v : 'system';
    }
    catch {
        return 'system';
    }
}
export function useTheme() {
    const [theme, setTheme] = useState(read);
    const choose = (t) => {
        setTheme(t);
        if (t === 'system')
            delete document.documentElement.dataset.theme;
        else
            document.documentElement.dataset.theme = t;
        try {
            if (t === 'system')
                localStorage.removeItem(KEY);
            else
                localStorage.setItem(KEY, t);
        }
        catch {
            // Not remembered; the choice still applies for this visit.
        }
    };
    return [theme, choose];
}
