/*
 * LD_PRELOAD shim for GitKraken Desktop's NSFW (Node Sentinel File Watcher,
 * @axosoft/nsfw -> nsfw.node). Redirects recursive InotifyNode::isDirectory
 * stat64() calls to lstat64() so symlinked dirs and build dirs are not crawled.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

typedef int (*stat64_fn_t)(const char *, struct stat64 *);
typedef int (*stat_fn_t)(const char *, struct stat *);
typedef int (*xstat64_fn_t)(int, const char *, struct stat64 *);
typedef int (*xstat_fn_t)(int, const char *, struct stat *);

static bool is_nsfw_caller(const void *ret_addr) {
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

static bool has_dotgit_entry(const char *path, stat64_fn_t real_lstat64_fn) {
    char dotgit[PATH_MAX];
    int written = snprintf(dotgit, sizeof(dotgit), "%s/.git", path);
    if (written <= 0 || (size_t)written >= sizeof(dotgit)) {
        return false;
    }
    struct stat64 dg_buf;
    return real_lstat64_fn(dotgit, &dg_buf) == 0;
}

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

static bool is_ignored_dir_name(const char *path) {
    size_t base_len = 0;
    const char *base = path_basename(path, &base_len);
    if (base_len == 0) {
        return false;
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

    if (S_ISLNK(buf->st_mode)) {
        /*
         * If <path>/.git exists, <path> is the root of a repository or worktree
         * reached via a symlink (InotifyTree root check). Follow it with stat64.
         * Otherwise <path> is a child symlink (e.g. bazel-out, bazel-bin); keep
         * S_ISLNK from lstat64 so InotifyNode::isDirectory returns false.
         */
        if (has_dotgit_entry(path, real_lstat64_fn)) {
            return real_stat64_fn(path, buf);
        }
        return 0;
    }

    if (S_ISDIR(buf->st_mode) && is_ignored_dir_name(path) && !has_dotgit_entry(path, real_lstat64_fn)) {
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
