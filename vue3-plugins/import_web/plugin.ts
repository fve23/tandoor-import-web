import {TandoorPlugin} from "@/types/Plugins.ts";
import {VListItem} from "vuetify/components";
import en from "@/plugins/import_web/locales/en.json";

const plugin: TandoorPlugin = {
    name: "import_web",
    basePath: "import_web",
    defaultLocale: Promise.resolve(en),
    localeFiles: import.meta.glob('@/plugins/import_web/locales/*.json'),
    routes: [
        {
            path: '/import-web',
            component: () => import("@/plugins/import_web/ImportWebPage.vue"),
            name: 'ImportWebPage',
            meta: {title: 'ImportWeb.NavTitle'},
        },
    ],
    settingRoutes: [],
    navigationDrawer: [
        {component: VListItem, prependIcon: 'fa-solid fa-file-import', title: 'ImportWeb.NavTitle', to: {name: 'ImportWebPage', params: {}}},
    ],
    bottomNavigation: [
        {component: VListItem, prependIcon: 'fa-solid fa-file-import', title: 'ImportWeb.NavTitle', to: {name: 'ImportWebPage', params: {}}},
    ],
    userNavigation: [],
};

export {plugin};
export default plugin;
