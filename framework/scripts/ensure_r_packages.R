#!/usr/bin/env Rscript
# Install the R packages the AoU/BigQuery run path needs — binaries when we can,
# and only the ones that are actually missing. Idempotent: safe to run every
# `make setup-workspace`. Local-only deps (duckdb, Eunomia) are NOT here; see
# GETTING_STARTED.md for the laptop set.

pkgs <- c("DBI", "bigrquery", "digest", "yaml")

missing <- setdiff(pkgs, rownames(installed.packages()))
if (length(missing) == 0) {
  message("R packages: all present (", paste(pkgs, collapse = ", "), ") — nothing to install.")
  quit(status = 0)
}

# --- pick a repo that serves precompiled Linux binaries -----------------------
# Posit Public Package Manager (P3M) serves binaries only when BOTH hold:
#   1. the URL names the distro:  .../__linux__/<codename>/latest
#   2. the HTTP User-Agent advertises the R version/platform (set below)
# Without (2) you silently get source tarballs that compile slowly.
read_os_release <- function() {
  f <- "/etc/os-release"
  if (!file.exists(f)) return(list())
  lines <- readLines(f, warn = FALSE)
  lines <- lines[grepl("=", lines, fixed = TRUE)]
  parts <- strsplit(lines, "=", fixed = TRUE)
  vals <- vapply(parts, function(p) gsub('^"|"$', "", paste(p[-1], collapse = "=")), character(1))
  stats::setNames(as.list(vals), vapply(parts, `[`, character(1), 1L))
}

repo <- Sys.getenv("R_PKG_REPO", "")  # explicit override wins
if (!nzchar(repo)) {
  codename <- read_os_release()[["VERSION_CODENAME"]]
  if (!is.null(codename) && nzchar(codename)) {
    repo <- sprintf("https://packagemanager.posit.co/cran/__linux__/%s/latest", codename)
    # Tell P3M which R/platform we are, so it hands back binaries.
    options(HTTPUserAgent = sprintf(
      "R/%s R (%s)", getRversion(),
      paste(getRversion(), R.version$platform, R.version$arch, R.version$os)
    ))
  } else {
    repo <- "https://cloud.r-project.org"  # source fallback; binaries unknown
    message("Could not detect a Linux codename; falling back to source from ", repo)
  }
}

# --- pick a writable library ---------------------------------------------------
# In AoU the site library (e.g. /opt/conda/.../lib/R/library) is read-only, so
# fall back to the per-user library. R puts R_LIBS_USER on .libPaths() at
# startup only if the directory exists, so creating it here makes later
# Rscript runs find these packages with no extra config.
is_writable <- function(p) dir.exists(p) && file.access(p, 2) == 0
lib <- Find(is_writable, .libPaths())
if (is.null(lib)) {
  lib <- path.expand(strsplit(Sys.getenv("R_LIBS_USER"), .Platform$path.sep)[[1]][1])
  dir.create(lib, recursive = TRUE, showWarnings = FALSE)
  .libPaths(c(lib, .libPaths()))
  message("Site library not writable; installing into user library ", lib)
}

message("Installing missing R packages from ", repo, " into ", lib, ": ",
        paste(missing, collapse = ", "))
install.packages(missing, lib = lib, repos = repo)

# Fail loudly if anything didn't actually land (e.g. a binary that won't load).
still_missing <- setdiff(missing, rownames(installed.packages()))
if (length(still_missing) > 0) {
  stop("R packages failed to install: ", paste(still_missing, collapse = ", "))
}
message("R packages ready: ", paste(pkgs, collapse = ", "))
