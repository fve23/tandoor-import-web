<template>
    <v-container>
        <v-row>
            <v-col v-if="!previewRecipe" cols="12" md="8">
                <v-card
                    :title="$t('ImportWeb.PageTitle')"
                    :subtitle="$t('ImportWeb.PageSubtitle')"
                    prepend-icon="fa-solid fa-globe"
                    variant="outlined"
                    elevation="1">
                    <v-card-text>
                        <v-text-field
                            v-model="importUrl"
                            :label="$t('ImportWeb.UrlLabel')"
                            variant="outlined"
                            clearable
                            :loading="loading"
                            autofocus
                            @keydown.enter="loadRecipeFromUrl"
                        ></v-text-field>

                        <v-alert
                            v-if="importResponse.error"
                            :title="$t('Error')"
                            :text="importResponse.msg"
                            color="warning"
                            variant="tonal"></v-alert>

                        <v-alert
                            v-if="imported"
                            :title="$t('Imported')"
                            :text="importedName + '  #' + importedId"
                            color="success"
                            variant="tonal"></v-alert>
                    </v-card-text>
                    <v-card-actions>
                        <v-btn
                            :disabled="importUrl === ''"
                            :loading="loading"
                            color="primary"
                            prepend-icon="fa-solid fa-download"
                            @click="loadRecipeFromUrl">{{ $t('Load') }}
                        </v-btn>
                    </v-card-actions>
                </v-card>

                <v-card
                    :title="$t('ImportWeb.VideoTitle')"
                    :subtitle="$t('ImportWeb.VideoSubtitle')"
                    prepend-icon="fa-solid fa-video"
                    variant="outlined"
                    elevation="1"
                    class="mt-4">
                    <v-card-text>
                        <v-text-field
                            v-model="videoUrl"
                            :label="$t('ImportWeb.VideoUrlLabel')"
                            variant="outlined"
                            clearable
                            :loading="loadingVideo"
                            @keydown.enter="loadRecipeFromVideo"
                        ></v-text-field>

                        <v-progress-liner
                            v-if="loadingVideo"
                            color="primary"
                            class="mt-2"
                            height="4"
                            indeterminate></v-progress-liner>
                        <div
                            v-if="loadingVideo"
                            class="mt-2 d-flex align-center ga-2" style="font-size: 0.85rem;">
                            <v-icon size="small" color="primary" class="mt-1 fa-spin" icon="fa-solid fa-spinner"></v-icon>
                            <span>{{ videoStatusText }}</span>
                        </div>

                        <v-alert
                            v-if="importResponse.error"
                            :title="$t('Error')"
                            :text="importResponse.msg"
                            color="warning"
                            variant="tonal"></v-alert>
                    </v-card-text>
                    <v-card-actions>
                        <v-btn
                            :disabled="videoUrl === ''"
                            :loading="loadingVideo"
                            color="primary"
                            prepend-icon="fa-solid fa-clapperboard"
                            @click="loadRecipeFromVideo">{{ $t('Load') }}
                        </v-btn>
                    </v-card-actions>
                </v-card>
            </v-col>
        </v-row>

        <v-row v-if="previewRecipe">
            <v-col cols="12" md="6">
                <h2 class="text-h5 mt-0">{{ $t('ImportWeb.PreviewEdit') }}</h2>
            </v-col>
            <v-col cols="12" md="6" class="text-end d-flex align-center ga-2">
                <v-btn
                    variant="tonal"
                    density="comfortable"
                    prepend-icon="$close"
                    @click="cancelPreview">{{ $t('Cancel') }}
                </v-btn>
                <v-btn
                    color="success"
                    density="comfortable"
                    :loading="saving"
                    prepend-icon="$save"
                    @click="createRecipeFromImport">{{ $t('ImportWeb.SaveRecipe') }}
                </v-btn>
            </v-col>
        </v-row>

        <template v-if="previewRecipe">
            <v-row>
                <v-col cols="12" md="4">
                    <v-card variant="outlined">
                        <div class="d-flex align-center justify-center" style="min-height: 160px;">
                            <img
                                v-if="previewImage"
                                :src="previewImage"
                                :alt="previewRecipe.name"
                                style="max-width: 100%; max-height: 30vh; width: 100%; object-fit: cover; display: block;">
                            <v-icon v-else size="48" icon="fa-solid fa-image" class="text-medium-emphasis"></v-icon>
                        </div>
                        <v-card-text v-if="importResponse.images && importResponse.images.length">
                            <div class="text-caption mb-1">{{ $t('ImportWeb.ChooseImage') }}</div>
                            <v-row dense>
                                <v-col cols="4" v-for="(u, idx) in importResponse.images" :key="idx">
                                    <v-img
                                        :src="imageSrc(u)"
                                        cover
                                        aspect-ratio="1"
                                        max-height="8vh"
                                        style="cursor: pointer;"
                                        :class="selectedImageUrl === u ? 'image-selected' : 'image-unselected'"
                                        @click="selectImage(u)"
                                    ></v-img>
                                </v-col>
                            </v-row>
                        </v-card-text>
                        <v-card-actions>
                            <v-btn
                                variant="text"
                                size="small"
                                prepend-icon="fa-solid fa-upload"
                                @click="triggerFileInput">{{ $t('ImportWeb.Upload') }}
                            </v-btn>
                            <v-btn
                                variant="text"
                                size="small"
                                color="error"
                                prepend-icon="$delete"
                                @click="removeImage"
                                :disabled="!previewRecipe.imageUrl && !customImageFile">{{ $t('Remove') }}
                            </v-btn>
                            <input
                                ref="fileInput"
                                type="file"
                                accept="image/*"
                                class="d-none"
                                @change="onImageFileSelected"
                            />
                        </v-card-actions>
                    </v-card>
                </v-col>
                <v-col cols="12" md="8">
                    <v-text-field
                        v-model="previewRecipe.name"
                        :label="$t('Name')"
                        variant="outlined"
                        :rules="[['maxLength', 128]]"
                        class="mb-2">
                    </v-text-field>
                    <v-textarea
                        v-model="previewRecipe.description"
                        :label="$t('Description')"
                        variant="outlined"
                        auto-grow
                        rows="2"
                        clearable
                        class="mb-2">
                    </v-textarea>
                    <v-row dense>
                        <v-col cols="6"><v-card variant="tonal" flat><v-card-text><v-icon icon="$servings" class="me-2"></v-icon>{{ previewRecipe.servings }} {{ previewRecipe.servingsText }}</v-card-text></v-card></v-col>
                        <v-col cols="3"><v-card variant="tonal" flat><v-card-text><v-icon icon="$work" class="me-2"></v-icon>{{ $t('ImportWeb.PrepLabel', {time: previewRecipe.workingTime}) }}</v-card-text></v-card></v-col>
                        <v-col cols="3"><v-card variant="tonal" flat><v-card-text><v-icon icon="$wait" class="me-2"></v-icon>{{ $t('ImportWeb.WaitLabel', {time: previewRecipe.waitingTime}) }}</v-card-text></v-card></v-col>
                    </v-row>
                    <div v-if="previewRecipe.keywords && previewRecipe.keywords.length" class="mt-2">
                        <div class="text-caption mb-1">{{ $t('Keywords') }} ({{ $t('ImportWeb.ToImport') }})</div>
                        <v-chip-group column dense>
                            <v-chip
                                v-for="k in previewRecipe.keywords"
                                :key="k.name"
                                :color="k.importKeyword !== false ? 'primary' : undefined"
                                :variant="k.importKeyword !== false ? 'flat' : 'outlined'"
                                @click="toggleKeyword(k)">{{ k.label }}</v-chip>
                        </v-chip-group>
                    </div>
                    <div v-if="importResponse.duplicates && importResponse.duplicates.length" class="mt-3">
                        <v-alert color="warning" variant="tonal" title="" density="compact">
                            <template #title><span class="text-subtitle-2">{{ $t('Duplicate') }}</span></template>
                            <v-list density="compact" lines="one" class="bg-none">
                                <v-list-item v-for="r in importResponse.duplicates" :key="r.id" :title="r.name + ' (#' + r.id + ')'"
                                            :to="{name: 'RecipeViewPage', params: {id: r.id}}" target="_blank"></v-list-item>
                            </v-list>
                        </v-alert>
                    </div>
                </v-col>
            </v-row>

            <v-row>
                <v-col cols="12">
                    <div class="d-flex align-center mb-1">
                        <h3 class="text-h6">{{ $t('Steps') }}</h3>
                        <v-spacer></v-spacer>
                        <v-btn variant="tonal" density="compact" prepend-icon="fa-solid fa-plus" @click="addStep">{{ $t('ImportWeb.AddStep') }}</v-btn>
                    </div>
                </v-col>
            </v-row>
            <v-row dense>
                <v-col v-for="(step, i) in previewRecipe.steps" :key="i" cols="12">
                    <v-card variant="outlined" class="mb-2">
                        <v-card-title class="d-flex align-center" density="compact">
                            <v-chip color="primary">#{{ i + 1 }}</v-chip>
                            <v-spacer></v-spacer>
                            <v-btn icon variant="plain" size="small" color="error" aria-label="delete-step" @click="deleteStep(step)">
                                <v-icon icon="$delete"></v-icon>
                            </v-btn>
                        </v-card-title>
                        <v-card-text>
                            <v-textarea
                                v-model="step.instruction"
                                :label="$t('Step')"
                                variant="outlined"
                                auto-grow
                                density="compact"
                                class="mb-2">
                            </v-textarea>
                            <v-divider class="my-2" v-if="step.ingredients && step.ingredients.length">
                                <span class="text-caption">{{ $t('ImportWeb.IngredientsEditable') }}</span>
                            </v-divider>
                            <div class="d-flex flex-column" v-if="step.ingredients && step.ingredients.length">
                                <div v-for="(ing, j) in step.ingredients" :key="j" class="d-flex flex-wrap align-center pa-1" style="gap:6px">
                                    <v-text-field
                                        v-model.number="ing.amount"
                                        type="number"
                                        variant="outlined"
                                        density="compact"
                                        :label="$t('Amount')"
                                        hide-details
                                        :clearable="true"
                                        class="amount-input"
                                        style="width:120px;flex:0 0 auto"
                                    />
                                    <v-text-field
                                        :model-value="ing.unit ? (ing.unit.name || '') : ''"
                                        variant="outlined"
                                        density="compact"
                                        :label="$t('Unit')"
                                        hide-details
                                        :clearable="true"
                                        @update:model-value="(v: string) => setIngredientUnit(ing, v)"
                                        style="width:120px;flex:0 0 auto"
                                    />
                                    <v-text-field
                                        :model-value="ing.food ? (ing.food.name || '') : ''"
                                        variant="outlined"
                                        density="compact"
                                        :label="$t('Food')"
                                        hide-details
                                        @update:model-value="(v: string) => setIngredientFood(ing, v)"
                                        style="flex:1 1 180px;min-width:150px"
                                    />
                                    <v-text-field
                                        v-model="ing.note"
                                        variant="outlined"
                                        density="compact"
                                        :label="$t('Note')"
                                        hide-details
                                        :clearable="true"
                                        style="flex:1 1 140px;min-width:120px"
                                    />
                                    <v-btn
                                        icon="mdi-close-circle"
                                        variant="text"
                                        size="small"
                                        color="error"
                                        @click="deleteIngredient(step, j)"
                                    />
                                </div>
                            </div>
                            <div class="d-flex justify-end pa-2">
                                <v-btn
                                    prepend-icon="mdi-plus"
                                    size="small"
                                    variant="tonal"
                                    color="primary"
                                    @click="addIngredient(step)"
                                >
                                    {{ $t('Add') }} {{ $t('Ingredient') }}
                                </v-btn>
                            </div>
                        </v-card-text>
                    </v-card>
                </v-col>
            </v-row>
        </template>

    </v-container>
</template>

<script lang="ts" setup>
import {computed, ref, onMounted} from "vue";
import {useRouter} from "vue-router";
import {useI18n} from "vue-i18n";
import {
    ApiApi,
    RecipeFromSourceResponse,
    RecipeFromSourceResponseFromJSON,
    SourceImportRecipe,
    SourceImportStep,
    SourceImportIngredient,
    SourceImportKeyword,
} from "@/openapi";
import {getCookie} from "@/utils/cookie";
import {useDjangoUrls} from "@/composables/useDjangoUrls";
import {useFileApi} from "@/composables/useFileApi";
import {ErrorMessageType, MessageType, PreparedMessage, useMessageStore} from "@/stores/MessageStore";

const router = useRouter()
const {t} = useI18n()
const {getDjangoUrl} = useDjangoUrls()
const {updateRecipeImage} = useFileApi()
const messageStore = useMessageStore()

const importUrl = ref("")
const videoUrl = ref("")
const loading = ref(false)
const loadingVideo = ref(false)
const videoStage = ref<'idle' | 'transcribe' | 'extract'>('idle')
const saving = ref(false)
const importResponse = ref({} as RecipeFromSourceResponse)
const previewRecipe = ref<SourceImportRecipe | null>(null)
const videoStatusText = computed(() => videoStage.value === 'extract' ? t('ImportWeb.VideoStatusExtract') : t('ImportWeb.VideoStatusTranscribe'))

// Image selection state. `previewRecipe.imageUrl` holds the chosen image (either
// a same-origin /import-web/image/ local-cache URL, a remote http URL, or '' if
// removed). `customImageFile` holds a locally-chosen file that overrides it.
const customImageFile = ref<File | null>(null)
const customImagePreview = ref("")
const imageTouched = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

function imageSrc(u: string): string {
    if (typeof u === 'string' && u.startsWith('/import-web/image/')) {
        return getDjangoUrl(u)
    }
    return u
}

const previewImage = computed(() => {
    if (customImagePreview.value) {
        return customImagePreview.value
    }
    const u = previewRecipe.value && previewRecipe.value.imageUrl
    if (typeof u === 'string' && u.startsWith('/import-web/image/')) {
        return getDjangoUrl(u)
    }
    return (typeof u === 'string' ? u : "")
})

const selectedImageUrl = computed(() => (previewRecipe.value && previewRecipe.value.imageUrl) || "")

function triggerFileInput() {
    fileInput.value && (fileInput.value as HTMLInputElement).click()
}

function onImageFileSelected(e: Event) {
    const input = e.target as HTMLInputElement
    const file = input.files && input.files[0]
    if (file) {
        if (customImagePreview.value) {
            URL.revokeObjectURL(customImagePreview.value)
        }
        customImageFile.value = file
        customImagePreview.value = URL.createObjectURL(file)
        imageTouched.value = true
    }
    input.value = ""
}

function selectImage(u: string) {
    if (previewRecipe.value) {
        previewRecipe.value.imageUrl = u
    }
    if (customImagePreview.value) {
        URL.revokeObjectURL(customImagePreview.value)
    }
    customImageFile.value = null
    customImagePreview.value = ""
    imageTouched.value = true
}

function removeImage() {
    if (previewRecipe.value) {
        previewRecipe.value.imageUrl = ""
    }
    if (customImagePreview.value) {
        URL.revokeObjectURL(customImagePreview.value)
    }
    customImageFile.value = null
    customImagePreview.value = ""
    imageTouched.value = true
}

const imported = ref(false)
const importedName = ref("")
const importedId = ref(0)

const params = new URLSearchParams(window.location.search)
onMounted(() => {
    const urlParam = params.get('url')
    if (urlParam) {
        importUrl.value = urlParam
        loadRecipeFromUrl()
    }
})

function formatIngredient(ing: any) {
    const bits: string[] = []
    if (ing.amount != null) bits.push(String(ing.amount))
    if (ing.food && ing.food.name) bits.push(ing.food.name)
    if (ing.unit && ing.unit.name) bits.push(ing.unit.name)
    if (ing.note) bits.push('(' + ing.note + ')')
    return bits.join(' ') || (ing.originalText || '')
}

function setIngredientFood(ing: SourceImportIngredient, value: string) {
    ing.food = {name: value}
}

function setIngredientUnit(ing: SourceImportIngredient, value: string) {
    ing.unit = {name: value}
}

function addIngredient(step: SourceImportStep) {
    step.ingredients.push({
        amount: null as any,
        food: {name: ''},
        unit: {name: ''},
        note: '',
        order: null,
        originalText: '',
    } as SourceImportIngredient)
}

function deleteIngredient(step: SourceImportStep, index: number) {
    step.ingredients.splice(index, 1)
}

// The Tandoor serializer requires a numeric amount on every ingredient. LLM
// output (and some scrapers) may omit it, which then breaks the save call.
function normalizeIngredients(recipe: SourceImportRecipe) {
    if (!recipe || !recipe.steps) {
        return
    }
    recipe.steps.forEach(step => {
        if (!step.ingredients) {
            step.ingredients = []
        }
        step.ingredients.forEach(ing => {
            if (ing.amount == null || isNaN(ing.amount)) {
                ing.amount = 1
            }
        })
    })
}

function toggleKeyword(k: SourceImportKeyword) {
    k.importKeyword = (k.importKeyword === false) ? true : false
}

function addStep() {
    if (previewRecipe.value) {
        previewRecipe.value.steps.push({ingredients: [], instruction: ''} as SourceImportStep)
    }
}

function deleteStep(step: SourceImportStep) {
    const steps = previewRecipe.value && previewRecipe.value.steps
    if (steps) {
        steps.splice(steps.findIndex(x => x === step), 1)
    }
}

function cancelPreview() {
    if (customImagePreview.value) {
        URL.revokeObjectURL(customImagePreview.value)
    }
    previewRecipe.value = null
    importResponse.value = {} as RecipeFromSourceResponse
    customImageFile.value = null
    customImagePreview.value = ""
    imageTouched.value = false
    videoStage.value = 'idle'
}

function loadRecipeFromUrl() {
    if (!importUrl.value.trim()) {
        return
    }
    loading.value = true
    imported.value = false
    importResponse.value = {} as RecipeFromSourceResponse
    previewRecipe.value = null
    customImageFile.value = null
    customImagePreview.value = ""
    imageTouched.value = false

    try {
        new URL(importUrl.value)
    } catch (e) {
        importUrl.value = "https://" + importUrl.value
    }

    const url = getDjangoUrl('import-web/recipe-from-source/')
    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken') as string,
        },
        body: JSON.stringify({url: importUrl.value}),
    }).then(r => {
        return r.json().then(json => {
            importResponse.value = RecipeFromSourceResponseFromJSON(json)
            if (importResponse.value.recipe) {
                previewRecipe.value = importResponse.value.recipe
                if (previewRecipe.value.keywords) {
                    previewRecipe.value.keywords.forEach(k => {
                        if (k.importKeyword === undefined) {
                            k.importKeyword = true
                        }
                    })
                }
                normalizeIngredients(previewRecipe.value)
            }
        })
    }).catch(err => {
        messageStore.addError(ErrorMessageType.FETCH_ERROR, err)
    }).finally(() => {
        loading.value = false
    })
}

function videoHeaders() {
    return {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken') as string,
    }
}

function loadRecipeFromVideo() {
    if (!videoUrl.value.trim()) {
        return
    }
    loadingVideo.value = true
    videoStage.value = 'transcribe'
    imported.value = false
    importResponse.value = {} as RecipeFromSourceResponse
    previewRecipe.value = null
    customImageFile.value = null
    customImagePreview.value = ""
    imageTouched.value = false

    let urlValue = videoUrl.value
    try {
        new URL(urlValue)
    } catch (e) {
        urlValue = "https://" + urlValue
    }

    fetch(getDjangoUrl('import-web/recipe-from-video/transcribe/'), {
        method: 'POST',
        headers: videoHeaders(),
        body: JSON.stringify({url: urlValue}),
    }).then(r => r.json().then(json => ({ok: r.ok, json}))).then(({ok, json}) => {
        if (!ok) {
            throw new Error(json.msg || t('Error'))
        }
        if (!json.text) {
            throw new Error(t('ImportWeb.VideoNoTranscript'))
        }
        const images = json.image_url ? [json.image_url] : []

        videoStage.value = 'extract'
        return fetch(getDjangoUrl('import-web/recipe-from-video/extract/'), {
            method: 'POST',
            headers: videoHeaders(),
            body: JSON.stringify({transcript: json.text, url: urlValue}),
        }).then(r2 => r2.json().then(json2 => ({ok: r2.ok, json: json2}))).then(({ok: ok2, json: json2}) => {
            if (!ok2) {
                throw new Error(json2.msg || t('Error'))
            }
            importResponse.value = RecipeFromSourceResponseFromJSON(json2)
            if (json2.images && json2.images.length === 0 && images.length > 0) {
                importResponse.value.images = images
            }
            if (importResponse.value.recipe) {
                previewRecipe.value = importResponse.value.recipe
                if (!previewRecipe.value.imageUrl && images.length > 0) {
                    previewRecipe.value.imageUrl = images[0]
                }
                if (previewRecipe.value.keywords) {
                    previewRecipe.value.keywords.forEach(k => {
                        if (k.importKeyword === undefined) {
                            k.importKeyword = true
                        }
                    })
                }
                normalizeIngredients(previewRecipe.value)
            }
        })
    }).catch(err => {
        messageStore.addError(ErrorMessageType.FETCH_ERROR, err)
    }).finally(() => {
        loadingVideo.value = false
        videoStage.value = 'idle'
    })
}

// Resolve the currently-selected image (previewRecipe.imageUrl) to a same-origin
// /import-web/image/ URL (the local disk cache) so we can download its bytes and
// upload them as a File on save. Returns "" when the selection is not a local cache
// entry (i.e. the user picked a remote URL or removed the image).
function localImageUrl(): string {
    const s = previewRecipe.value && previewRecipe.value.imageUrl
    if (typeof s === 'string' && s.startsWith('/import-web/image/')) {
        return getDjangoUrl(s)
    }
    return ""
}

function localImageExtension(blobType: string): string {
    const t = (blobType || '').toLowerCase()
    if (t.includes('png')) return '.png'
    if (t.includes('webp')) return '.webp'
    if (t.includes('gif')) return '.gif'
    if (t.includes('svg')) return '.svg'
    return '.jpg'
}

function loadLocalImageFile(): Promise<File | null> {
    const source = localImageUrl()
    if (!source) {
        return Promise.resolve(null)
    }
    return fetch(source).then(r => {
        if (!r.ok) {
            return null as File | null
        }
        return r.blob()
    }).then(blob => {
        if (!blob || blob.size === 0) {
            return null as File | null
        }
        return new File([blob], 'imported-image' + localImageExtension(blob.type), {type: blob.type || 'image/jpeg'})
    }).catch(() => {
        return null as File | null
    })
}

function createRecipeFromImport() {
    if (!previewRecipe.value) {
        return
    }
    saving.value = true
    const recipe = previewRecipe.value as SourceImportRecipe
    if (recipe.keywords) {
        recipe.keywords = recipe.keywords.filter(k => k.importKeyword !== false)
    }
    // Only auto-fill the image from the first detected candidate when the user
    // did not explicitly remove/change it on this screen.
    if (!imageTouched.value && !recipe.imageUrl && importResponse.value.images && importResponse.value.images.length > 0) {
        recipe.imageUrl = importResponse.value.images[0]
    }

    let api = new ApiApi()
    const navigate = (id: number) => router.push({name: 'RecipeViewPage', params: {id: id}})

    api.apiRecipeCreate({recipe: recipe}).then(async created => {
        messageStore.addPreparedMessage(PreparedMessage.CREATE_SUCCESS)
        if (customImageFile.value) {
            // The user picked a local file - upload those bytes directly.
            await updateRecipeImage(created.id!, customImageFile.value, undefined)
        } else {
            const imageFile = await loadLocalImageFile()
            if (imageFile) {
                // Selected image is our local disk cache: forward the already-
                // fetched bytes instead of asking the server to re-fetch.
                await updateRecipeImage(created.id!, imageFile, undefined)
            } else if (typeof recipe.imageUrl === 'string' && recipe.imageUrl.startsWith('http')) {
                // No local cache (user picked a remote URL, or the plugin could
                // not fetch the image). Let the server download it.
                await updateRecipeImage(created.id!, null, recipe.imageUrl)
            }
        }
        navigate(created.id!)
    }).catch(err => {
        messageStore.addError(ErrorMessageType.CREATE_ERROR, err)
    }).finally(() => {
        saving.value = false
    })
}
</script>

<style scoped>
.image-selected {
    outline: 2px solid var(--v-theme-primary);
    outline-offset: 1px;
    border-radius: 4px;
}
.image-unselected {
    outline: 1px solid rgba(0, 0, 0, 0.15);
    border-radius: 4px;
}
.amount-input :deep(input[type="number"]) {
    -moz-appearance: textfield;
    appearance: textfield;
}
.amount-input :deep(input[type="number"]::-webkit-inner-spin-button),
.amount-input :deep(input[type="number"]::-webkit-outer-spin-button) {
    -webkit-appearance: none;
    appearance: none;
    margin: 0;
}
</style>
