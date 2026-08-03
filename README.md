# k8s-feature-blogs

Live status page for Kubernetes v1.37 Feature Blog PRs, sourced from the
[Release Tracking project board](https://github.com/orgs/kubernetes/projects/264/views/5)
(Blog Status column). Rebuilds every 6 hours via GitHub Actions and publishes
to GitHub Pages from `docs/`.

## Setup (one-time, required)

The default `GITHUB_TOKEN` cannot read GitHub Projects (v2) via GraphQL, so
the workflow needs a **classic** Personal Access Token (fine-grained tokens
can't resolve an org as a Projects v2 owner and will fail with
`unknown owner type`):

1. Create a classic PAT: https://github.com/settings/tokens/new
   scopes: `repo`, `read:project`, `read:org`
   (`read:org` is required too — without it `gh project item-list --owner kubernetes`
   fails with `unknown owner type` since gh can't confirm `kubernetes` is an org.)
2. Add it as a repo secret named `PROJECT_TOKEN`:
   `gh secret set PROJECT_TOKEN --repo tineoc/k8s-feature-blogs`
3. Enable Pages: Settings -> Pages -> Source: `main` branch, `/docs` folder.

## Manual rebuild

```
make build   # regenerate docs/index.html + docs/data.json
make serve   # build + serve docs/ locally at :8000
make clean   # remove generated output
```

Requires `gh` CLI authenticated with the scopes above, and `python3`.
