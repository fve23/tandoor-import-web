// Build shim: useNavigation.ts:6 hard-imports this exact path with no guard,
// but vue3/src/plugins is gitignored and empty in our clone, so the build
// fails without it. This minimal stub satisfies the import (and the runtime
// TandoorPlugin contract) with zero tracked changes to the recipes/ clone; it
// is injected into the container via the docker-compose volume mount.
import {TandoorPlugin} from "@/types/Plugins.ts";

export let plugin: TandoorPlugin = {
    name: "open_data_plugin",
    basePath: "open-data",
    defaultLocale: Promise.resolve({}),
    localeFiles: {},
    routes: [],
    settingRoutes: [],
    navigationDrawer: [],
    bottomNavigation: [],
    userNavigation: []
}

export default plugin
