/*
 * LD_PRELOAD runtime shim for GitKraken Desktop (`libgk_preload_shim.so`).
 *
 * Loaded into the GitKraken process by `gitkraken-launcher` so `/usr/share/gitkraken/`
 * is never modified on disk. Interposes two families of glibc calls:
 *
 *   1. `stat64` / `stat` / `__xstat64` / `__xstat` (file-watcher scope pruning):
 *      GitKraken's file watcher (`nsfw.node`) walks directories with `stat64()`
 *      and recurses into every entry where `S_ISDIR(st_mode)` is true. When the
 *      caller's return address (`dladdr`) is inside `nsfw.node`, we resolve
 *      child entries with `lstat64()` so symlinks report `S_ISLNK` (stopping
 *      recursion into symlinked build caches) and rewrite directories matching
 *      `GK_IGNORED_DIRS` from `S_IFDIR` to `S_IFREG` so `nsfw.node` skips them.
 *
 *   2. `pread64` / `pread` / `read` (in-memory `app.asar` buffer patching):
 *      Does not modify `app.asar` on disk. When Electron reads bytes from a
 *      file descriptor whose `(st_dev, st_ino)` matches `app.asar`, libc first
 *      populates the caller's `void *buf` in RAM. Before returning to Electron,
 *      `patch_asar_buffer()` scans `buf` with `memmem()` and overwrites the
 *      commit detail panel transition variable (`base.jsonc`) and flexbox rule
 *      (`styles.css`) in-place with equal-length byte sequences so ASAR header
 *      offsets stay valid.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

typedef int (*stat64_fn_t)(const char *, struct stat64 *);
typedef int (*stat_fn_t)(const char *, struct stat *);
typedef int (*xstat64_fn_t)(int, const char *, struct stat64 *);
typedef int (*xstat_fn_t)(int, const char *, struct stat *);
typedef int (*fstat64_fn_t)(int, struct stat64 *);
typedef int (*fxstat64_fn_t)(int, int, struct stat64 *);
typedef ssize_t (*pread64_fn_t)(int, void *, size_t, off64_t);
typedef ssize_t (*pread_fn_t)(int, void *, size_t, off_t);
typedef ssize_t (*read_fn_t)(int, void *, size_t);

#define GK_DEFAULT_ASAR_PATH "/usr/share/gitkraken/resources/app.asar"

/*
 * In-memory replacements applied to `read`/`pread` buffers from `app.asar`:
 *   - `GK_CSS_*` (48 bytes): patches `.right-panel .inner-right-panel` in
 *     `src/css/styles.css` to add `min-width:0;overflow:hidden` and disable the
 *     transition.
 *   - `GK_THEME_*` (63 bytes): patches `src/main/static/themeBases/base.jsonc`
 *     (padded with spaces) so all built-in themes emit `transition: none`.
 * Each replacement must match its needle's exact byte length so file offsets in
 * the `app.asar` JSON header never shift.
 */
#define GK_CSS_NEEDLE "transition:var(--expand-detail-panel-transition)"
#define GK_CSS_REPLACEMENT "min-width:0;overflow:hidden;transition:none/***/"
#define GK_THEME_NEEDLE "\"expand-detail-panel-transition\": \"flex-grow 250ms ease-in-out\""
#define GK_THEME_REPLACEMENT "\"expand-detail-panel-transition\": \"none\"                       "

_Static_assert(
    sizeof(GK_CSS_NEEDLE) == sizeof(GK_CSS_REPLACEMENT),
    "GK_CSS_NEEDLE and GK_CSS_REPLACEMENT must have identical byte length"
);
_Static_assert(
    sizeof(GK_THEME_NEEDLE) == sizeof(GK_THEME_REPLACEMENT),
    "GK_THEME_NEEDLE and GK_THEME_REPLACEMENT must have identical byte length"
);

/* Calls libc stat64/xstat64 directly via RTLD_NEXT. */
static int call_real_stat64(const char *path, struct stat64 *buf) {
    static stat64_fn_t real_stat64_fn = NULL;
    static xstat64_fn_t real_xstat64_fn = NULL;
    if (real_stat64_fn == NULL) {
        real_stat64_fn = (stat64_fn_t)dlsym(RTLD_NEXT, "stat64");
    }
    if (real_stat64_fn != NULL) {
        return real_stat64_fn(path, buf);
    }
    if (real_xstat64_fn == NULL) {
        real_xstat64_fn = (xstat64_fn_t)dlsym(RTLD_NEXT, "__xstat64");
    }
    if (real_xstat64_fn != NULL) {
        return real_xstat64_fn(1, path, buf);
    }
    return -1;
}

/* Calls libc fstat64/fxstat64 directly via RTLD_NEXT. */
static int call_real_fstat64(int fd, struct stat64 *buf) {
    static fstat64_fn_t real_fstat64_fn = NULL;
    static fxstat64_fn_t real_fxstat64_fn = NULL;
    if (real_fstat64_fn == NULL) {
        real_fstat64_fn = (fstat64_fn_t)dlsym(RTLD_NEXT, "fstat64");
    }
    if (real_fstat64_fn != NULL) {
        return real_fstat64_fn(fd, buf);
    }
    if (real_fxstat64_fn == NULL) {
        real_fxstat64_fn = (fxstat64_fn_t)dlsym(RTLD_NEXT, "__fxstat64");
    }
    if (real_fxstat64_fn != NULL) {
        return real_fxstat64_fn(1, fd, buf);
    }
    return -1;
}

static bool is_active_gk_process(void);

/*
 * Identifies app.asar file descriptors by comparing (st_dev, st_ino) rather
 * than tracking open/close state, avoiding races when fd numbers are recycled.
 */
static bool is_app_asar_fd(int fd) {
    if (fd < 0 || !is_active_gk_process()) {
        return false;
    }
    struct stat64 fd_st;
    if (call_real_fstat64(fd, &fd_st) != 0 || !S_ISREG(fd_st.st_mode)) {
        return false;
    }
    const char *custom_asar = getenv("GK_ASAR_PATH");
    if (custom_asar != NULL && *custom_asar != '\0') {
        struct stat64 target_st;
        if (call_real_stat64(custom_asar, &target_st) != 0) {
            return false;
        }
        return fd_st.st_dev == target_st.st_dev && fd_st.st_ino == target_st.st_ino;
    }
    static dev_t cached_dev = 0;
    static ino64_t cached_ino = 0;
    static int cache_state = 0;
    if (cache_state == 0) {
        struct stat64 target_st;
        if (call_real_stat64(GK_DEFAULT_ASAR_PATH, &target_st) == 0) {
            cached_dev = target_st.st_dev;
            cached_ino = target_st.st_ino;
            cache_state = 1;
        } else {
            cache_state = -1;
        }
    }
    return cache_state == 1 && fd_st.st_dev == cached_dev && fd_st.st_ino == cached_ino;
}

/* Replaces all occurrences of `needle` (`pat_len` bytes) in `buf` in-place. */
static void replace_all_in_buffer(
    void *buf,
    size_t len,
    const char *needle,
    const char *replacement,
    size_t pat_len
) {
    char *cursor = (char *)buf;
    size_t remaining = len;
    while (remaining >= pat_len) {
        char *hit = (char *)memmem(cursor, remaining, needle, pat_len);
        if (hit == NULL) {
            break;
        }
        memcpy(hit, replacement, pat_len);
        size_t advance = (size_t)(hit - cursor) + pat_len;
        cursor += advance;
        remaining -= advance;
    }
}

/* Applies the in-memory CSS and theme variable patches to `app.asar` buffers. */
static void patch_asar_buffer(void *buf, ssize_t nread) {
    const size_t css_len = sizeof(GK_CSS_NEEDLE) - 1;
    const size_t theme_len = sizeof(GK_THEME_NEEDLE) - 1;
    if (buf == NULL || nread < (ssize_t)css_len) {
        return;
    }
    replace_all_in_buffer(
        buf, (size_t)nread, GK_CSS_NEEDLE, GK_CSS_REPLACEMENT, css_len
    );
    if ((size_t)nread >= theme_len) {
        replace_all_in_buffer(
            buf, (size_t)nread, GK_THEME_NEEDLE, GK_THEME_REPLACEMENT, theme_len
        );
    }
}

/*
 * Returns true when `ret_addr` originates inside `nsfw.node` so Node.js `fs`
 * and `libgit2` callers retain unmodified `stat` behavior.
 */
static bool is_nsfw_caller(const void *ret_addr) {
    if (!is_active_gk_process()) {
        return false;
    }
    const char *force = getenv("GK_NSFW_TEST_FORCE");
    if (force != NULL && strcmp(force, "1") == 0) {
        return true;
    }
    Dl_info info;
    if (ret_addr != NULL && dladdr(ret_addr, &info) != 0 && info.dli_fname != NULL) {
        return strstr(info.dli_fname, "nsfw.node") != NULL;
    }
    return false;
}

/*
 * Checks whether `<path>/.git` exists so symlinked repository roots remain
 * watchable while child symlinks inside the working tree are not followed.
 */
static bool has_dotgit_entry(const char *path, stat64_fn_t real_lstat64_fn) {
    char dotgit[PATH_MAX];
    int written = snprintf(dotgit, sizeof(dotgit), "%s/.git", path);
    if (written <= 0 || (size_t)written >= sizeof(dotgit)) {
        return false;
    }
    struct stat64 dg_buf;
    return real_lstat64_fn(dotgit, &dg_buf) == 0;
}

/* Returns the final path component and its length, ignoring trailing slashes. */
static const char *path_basename(const char *path, size_t *len_out) {
    size_t len = strlen(path);
    while (len > 1 && path[len - 1] == '/') {
        len--;
    }
    const char *slash = memrchr(path, '/', len);
    if (slash == NULL) {
        *len_out = len;
        return path;
    }
    const char *base = slash + 1;
    *len_out = (size_t)((path + len) - base);
    return base;
}

/*
 * Returns true only when loaded inside the `gitkraken` executable (or an
 * explicit unit-test harness setting `GK_NSFW_TEST_FORCE=1` / `GK_ASAR_PATH`).
 */
static bool is_active_gk_process(void) {
    static int state = 0;
    if (state != 0) {
        return state == 1;
    }
    const char *force = getenv("GK_NSFW_TEST_FORCE");
    if (force != NULL && strcmp(force, "1") == 0) {
        state = 1;
        return true;
    }
    const char *custom_asar = getenv("GK_ASAR_PATH");
    if (custom_asar != NULL && *custom_asar != '\0') {
        state = 1;
        return true;
    }
    char exe_path[PATH_MAX];
    ssize_t len = readlink("/proc/self/exe", exe_path, sizeof(exe_path) - 1);
    if (len > 0) {
        exe_path[len] = '\0';
        size_t base_len = 0;
        const char *base = path_basename(exe_path, &base_len);
        if (base_len == 9 && strncmp(base, "gitkraken", 9) == 0) {
            state = 1;
            return true;
        }
    }
    state = -1;
    return false;
}

/*
 * Strips `libgk_preload_shim.so` (and any `.so` under `gitkraken-optimizer/`)
 * from `LD_PRELOAD` so non-GitKraken child processes (such as integrated
 * terminal shells and git subprocesses) do not inherit or propagate the shim.
 */
static void strip_gk_shim_from_ld_preload(void) {
    const char *preload = getenv("LD_PRELOAD");
    if (preload == NULL || *preload == '\0') {
        return;
    }
    char cleaned[PATH_MAX * 2];
    size_t out_len = 0;
    const char *cur = preload;
    while (*cur != '\0') {
        while (*cur == ':' || *cur == ' ') {
            cur++;
        }
        if (*cur == '\0') {
            break;
        }
        const char *end = cur;
        while (*end != '\0' && *end != ':' && *end != ' ') {
            end++;
        }
        size_t tok_len = (size_t)(end - cur);
        bool is_gk_shim = (
            memmem(cur, tok_len, "libgk_preload_shim.so", 21) != NULL ||
            memmem(cur, tok_len, "gitkraken-optimizer/", 20) != NULL
        );
        if (!is_gk_shim) {
            if (out_len > 0 && out_len + 1 < sizeof(cleaned)) {
                cleaned[out_len++] = ':';
            }
            if (out_len + tok_len < sizeof(cleaned)) {
                memcpy(cleaned + out_len, cur, tok_len);
                out_len += tok_len;
            }
        }
        cur = end;
    }
    if (out_len == 0) {
        unsetenv("LD_PRELOAD");
    } else {
        cleaned[out_len] = '\0';
        setenv("LD_PRELOAD", cleaned, 1);
    }
}

__attribute__((constructor))
static void gk_shim_init(void) {
    if (!is_active_gk_process()) {
        strip_gk_shim_from_ld_preload();
    }
}

/*
 * Checks whether `path`'s basename is listed in colon-delimited `GK_IGNORED_DIRS`
 * or starts with `bazel-` (Bazel output symlinks).
 */
static bool is_ignored_dir_name(const char *path) {
    size_t base_len = 0;
    const char *base = path_basename(path, &base_len);
    if (base_len == 0) {
        return false;
    }
    if (base_len > 6 && strncmp(base, "bazel-", 6) == 0) {
        return true;
    }
    const char *dirs = getenv("GK_IGNORED_DIRS");
    if (dirs == NULL) {
        dirs = (
            "node_modules:.venv:.pixi:target:.cache:.pnpm-store:"
            ".mypy_cache:.ruff_cache:__pycache__:.pytest_cache"
        );
    }
    const char *cur = dirs;
    while (*cur != '\0') {
        const char *sep = strchr(cur, ':');
        size_t tok_len = (sep != NULL) ? (size_t)(sep - cur) : strlen(cur);
        if (tok_len == base_len && strncmp(cur, base, base_len) == 0) {
            return true;
        }
        if (sep == NULL) {
            break;
        }
        cur = sep + 1;
    }
    return false;
}

/*
 * Redirects nsfw.node lookups to lstat64 (preserving root symlinks that contain
 * `.git` while skipping child worktree symlinks) and masks ignored directories
 * as `S_IFREG` to stop recursion.
 */
static int handle_stat64_impl(
    const char *path,
    struct stat64 *buf,
    const void *ret_addr,
    stat64_fn_t real_stat64_fn,
    stat64_fn_t real_lstat64_fn
) {
    if (path == NULL || buf == NULL || !is_nsfw_caller(ret_addr)) {
        return real_stat64_fn(path, buf);
    }

    int rc = real_lstat64_fn(path, buf);
    if (rc != 0) {
        return rc;
    }

    bool ignored = is_ignored_dir_name(path);
    if (S_ISLNK(buf->st_mode)) {
        if (!ignored && has_dotgit_entry(path, real_lstat64_fn)) {
            return real_stat64_fn(path, buf);
        }
        return 0;
    }

    if (S_ISDIR(buf->st_mode) && ignored) {
        buf->st_mode = (buf->st_mode & ~S_IFMT) | S_IFREG;
    }
    return 0;
}

int stat64(const char *path, struct stat64 *buf) {
    static stat64_fn_t real_stat64_fn = NULL;
    static stat64_fn_t real_lstat64_fn = NULL;
    if (real_stat64_fn == NULL) {
        real_stat64_fn = (stat64_fn_t)dlsym(RTLD_NEXT, "stat64");
    }
    if (real_lstat64_fn == NULL) {
        real_lstat64_fn = (stat64_fn_t)dlsym(RTLD_NEXT, "lstat64");
    }
    return handle_stat64_impl(
        path, buf, __builtin_return_address(0), real_stat64_fn, real_lstat64_fn
    );
}

int stat(const char *path, struct stat *buf) {
    static stat_fn_t real_stat_fn = NULL;
    static stat64_fn_t real_stat64_fn = NULL;
    static stat64_fn_t real_lstat64_fn = NULL;
    if (real_stat_fn == NULL) {
        real_stat_fn = (stat_fn_t)dlsym(RTLD_NEXT, "stat");
    }
    if (real_stat64_fn == NULL) {
        real_stat64_fn = (stat64_fn_t)dlsym(RTLD_NEXT, "stat64");
    }
    if (real_lstat64_fn == NULL) {
        real_lstat64_fn = (stat64_fn_t)dlsym(RTLD_NEXT, "lstat64");
    }
    if (!is_nsfw_caller(__builtin_return_address(0))) {
        return real_stat_fn(path, buf);
    }
    struct stat64 b64;
    int rc = handle_stat64_impl(
        path, &b64, __builtin_return_address(0), real_stat64_fn, real_lstat64_fn
    );
    if (rc != 0) {
        return rc;
    }
    int real_rc = real_stat_fn(path, buf);
    if (real_rc != 0 && !S_ISLNK(b64.st_mode)) {
        return real_rc;
    }
    buf->st_mode = b64.st_mode;
    return 0;
}

/* Legacy glibc `_STAT_VER` ABI entry points used by prebuilt Node addons. */
int __xstat64(int ver, const char *path, struct stat64 *buf) {
    static xstat64_fn_t real_xstat64_fn = NULL;
    static stat64_fn_t real_stat64_fn = NULL;
    static stat64_fn_t real_lstat64_fn = NULL;
    if (real_xstat64_fn == NULL) {
        real_xstat64_fn = (xstat64_fn_t)dlsym(RTLD_NEXT, "__xstat64");
    }
    if (real_stat64_fn == NULL) {
        real_stat64_fn = (stat64_fn_t)dlsym(RTLD_NEXT, "stat64");
    }
    if (real_lstat64_fn == NULL) {
        real_lstat64_fn = (stat64_fn_t)dlsym(RTLD_NEXT, "lstat64");
    }
    if (!is_nsfw_caller(__builtin_return_address(0))) {
        if (real_xstat64_fn != NULL) {
            return real_xstat64_fn(ver, path, buf);
        }
        return real_stat64_fn(path, buf);
    }
    return handle_stat64_impl(
        path, buf, __builtin_return_address(0), real_stat64_fn, real_lstat64_fn
    );
}

int __xstat(int ver, const char *path, struct stat *buf) {
    static xstat_fn_t real_xstat_fn = NULL;
    if (real_xstat_fn == NULL) {
        real_xstat_fn = (xstat_fn_t)dlsym(RTLD_NEXT, "__xstat");
    }
    if (!is_nsfw_caller(__builtin_return_address(0))) {
        if (real_xstat_fn != NULL) {
            return real_xstat_fn(ver, path, buf);
        }
    }
    return stat(path, buf);
}

/* Intercepts app.asar reads (`pread64`/`pread`/`read`) to patch UI styles in RAM. */
ssize_t pread64(int fd, void *buf, size_t count, off64_t offset) {
    static pread64_fn_t real_pread64_fn = NULL;
    if (real_pread64_fn == NULL) {
        real_pread64_fn = (pread64_fn_t)dlsym(RTLD_NEXT, "pread64");
    }
    ssize_t nread = real_pread64_fn(fd, buf, count, offset);
    if (nread > 0 && is_app_asar_fd(fd)) {
        patch_asar_buffer(buf, nread);
    }
    return nread;
}

ssize_t pread(int fd, void *buf, size_t count, off_t offset) {
    static pread_fn_t real_pread_fn = NULL;
    if (real_pread_fn == NULL) {
        real_pread_fn = (pread_fn_t)dlsym(RTLD_NEXT, "pread");
    }
    ssize_t nread = real_pread_fn(fd, buf, count, offset);
    if (nread > 0 && is_app_asar_fd(fd)) {
        patch_asar_buffer(buf, nread);
    }
    return nread;
}

ssize_t read(int fd, void *buf, size_t count) {
    static read_fn_t real_read_fn = NULL;
    if (real_read_fn == NULL) {
        real_read_fn = (read_fn_t)dlsym(RTLD_NEXT, "read");
    }
    ssize_t nread = real_read_fn(fd, buf, count);
    if (nread > 0 && is_app_asar_fd(fd)) {
        patch_asar_buffer(buf, nread);
    }
    return nread;
}

