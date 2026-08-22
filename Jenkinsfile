// Nora Dataset — build, publish and deploy.
//
// Follows the house pipeline used by diis-itoc/psu-policy: agent none with a
// per-stage agent, the PSU registry addressed through the global $REGISTRY_URL,
// the shared ci-bot account with CI_REGISTRY_TOKEN, secrets delivered as a
// file credential holding a .env, and branches deciding what happens:
//
//   develop  lint, test, build, push          (no deployment target yet)
//   main     the same, then deploy to ainora-agent
//
// What this pipeline adds over that template: it records the running image
// before swapping it and rolls back automatically if the new one fails its
// health check, and it verifies after every deploy that the download gate
// still refuses an unauthenticated request.
//
// Bundle files are never touched here. They live on the server's data volume
// and are updated out of band with rsync.

pipeline {
    agent none

    environment {
        // REGISTRY_URL is a global Jenkins environment variable, as in the
        // psu-policy pipeline. Change the group below if this project is not
        // filed under diis-itoc.
        REGISTRY_NORA_IMAGE = "${REGISTRY_URL}/diis-itoc/nora-dataset"
        REGISTRY_USER       = 'ci-bot'
        VERSION             = '1.0.0'

        // Run from the checked-out workspace rather than a copy placed on the
        // host: the agent has no rights under /srv, and this way the compose
        // file that deploys is always the one from the commit being deployed.
        COMPOSE_FILE = 'deploy/docker-compose.yml'
        SERVICE      = 'dataset-web'
        CONTAINER    = 'ainora-dataset-web'

        // The service as the public sees it, through the host nginx. Only the
        // best-effort proxy check uses this: the agent is not assumed to be on
        // the same network as the published port, so every other check runs
        // inside the container.
        PUBLIC_URL = 'http://127.0.0.1/dataset'
    }

    options {
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }

    stages {

        stage('Checkout') {
            agent { label 'built-in' }
            when {
                anyOf {
                    branch 'develop'
                    branch 'main'
                }
            }
            steps {
                checkout scm
                script {
                    // Every image is tagged with the commit it was built from,
                    // so a rollback can name an exact build rather than "the
                    // one before latest".
                    env.SHORT_SHA = env.GIT_COMMIT.take(7)
                    echo "Building from ${env.GIT_COMMIT} (${env.SHORT_SHA})"
                }
            }
        }

        stage('Lint Dockerfile') {
            agent {
                docker {
                    image 'hadolint/hadolint:latest-debian'
                    label 'built-in'
                    args '-v $PWD:/workdir'
                }
            }
            when { branch 'develop' }
            steps {
                checkout scm
                sh 'hadolint --failure-threshold error Dockerfile > hadolint_report.txt'
            }
            post {
                always {
                    archiveArtifacts artifacts: 'hadolint_report.txt', allowEmptyArchive: true
                }
            }
        }

        stage('Checks & build') {
            when {
                anyOf {
                    branch 'develop'
                    branch 'main'
                }
            }
            parallel {

                stage('Lint & unit tests') {
                    agent {
                        docker {
                            image 'python:3.12'
                            label 'built-in'
                            args '-v $PWD:/app'
                        }
                    }
                    steps {
                        checkout scm
                        sh '''
                            set -eu
                            pip install --no-cache-dir -r requirements.txt \
                                ruff==0.8.4 pytest==8.3.4 httpx==0.28.1

                            ruff check app scripts tests
                            ruff format --check app scripts tests

                            # A throwaway key: the application refuses to start
                            # without one. The real key never leaves Jenkins
                            # credentials and is never a repository secret.
                            SECRET_KEY=ci-only-not-a-real-secret-padding-0000000000 \
                                python -m pytest tests -v --junitxml=pytest-report.xml
                        '''
                    }
                    post {
                        always {
                            // Archived rather than published through the JUnit
                            // plugin, to keep this pipeline's plugin
                            // requirements the same as psu-policy's.
                            archiveArtifacts artifacts: 'pytest-report.xml', allowEmptyArchive: true
                            cleanWs()
                        }
                    }
                }

                stage('Validate catalogue') {
                    agent {
                        docker {
                            image 'python:3.12'
                            label 'built-in'
                        }
                    }
                    steps {
                        checkout scm
                        // Guards against malformed JSON reaching production and
                        // against a bundle entry claiming a file the manifest
                        // does not describe.
                        sh 'python scripts/validate_catalog.py'
                    }
                    post { always { cleanWs() } }
                }

                stage('Build docker image') {
                    agent { label 'built-in' }
                    steps {
                        checkout scm
                        sh '''
                            set -eu
                            docker build \
                                -t "$REGISTRY_NORA_IMAGE:$VERSION" \
                                -t "$REGISTRY_NORA_IMAGE:$SHORT_SHA" \
                                -t "$REGISTRY_NORA_IMAGE:latest" \
                                .
                        '''
                    }
                }
            }
        }

        stage('Push image to registry') {
            agent { label 'built-in' }
            when {
                anyOf {
                    branch 'develop'
                    branch 'main'
                }
            }
            steps {
                withCredentials([string(
                    credentialsId: 'CI_REGISTRY_TOKEN',
                    variable: 'REGISTRY_TOKEN'
                )]) {
                    sh '''
                        set -eu
                        echo "$REGISTRY_TOKEN" | docker login -u "$REGISTRY_USER" --password-stdin "$REGISTRY_URL"
                        docker push "$REGISTRY_NORA_IMAGE:$VERSION"
                        docker push "$REGISTRY_NORA_IMAGE:$SHORT_SHA"
                        docker push "$REGISTRY_NORA_IMAGE:latest"
                    '''
                }
            }
            post {
                always { sh 'docker logout "$REGISTRY_URL" || true' }
            }
        }

        stage('Deploy to Production') {
            agent { label 'ainora-agent' }
            when { branch 'main' }
            steps {
                checkout scm

                withCredentials([
                    string(credentialsId: 'CI_REGISTRY_TOKEN', variable: 'REGISTRY_TOKEN'),
                    file(credentialsId: 'NORA_DATASET_ENV_PRODUCTION', variable: 'ENV_FILE')
                ]) {
                    script {
                        // Captured before anything changes, so the rollback in
                        // post{} has a concrete image to return to.
                        env.PREVIOUS_IMAGE = sh(
                            script: "docker inspect --format='{{.Config.Image}}' $CONTAINER 2>/dev/null || echo none",
                            returnStdout: true
                        ).trim()
                        echo "Currently running: ${env.PREVIOUS_IMAGE}"
                    }

                    sh '''
                        set -eu
                        echo "$REGISTRY_TOKEN" | docker login -u "$REGISTRY_USER" --password-stdin "$REGISTRY_URL"
                        docker pull "$REGISTRY_NORA_IMAGE:$SHORT_SHA"

                        cp "$ENV_FILE" .env.production
                        chmod 600 .env.production
                    '''

                    echo 'Deploying to Production'

                    // Storage is a named Docker volume, so there is nothing to
                    // create on the host first.
                    sh '''
                        set -eu

                        # No `down` first: --force-recreate swaps the container
                        # in place, so the gap is a restart rather than a window
                        # with nothing listening on 10095.
                        IMAGE="$REGISTRY_NORA_IMAGE:$SHORT_SHA" \
                            docker compose --env-file .env.production \
                                -f "$COMPOSE_FILE" up -d --force-recreate "$SERVICE"
                    '''

                    // Health is read from Docker, not from the host's
                    // loopback. The agent may not share a network namespace
                    // with the published port — it often runs as a container
                    // itself — and then curl to 127.0.0.1:10095 fails even
                    // though the service is perfectly healthy. The image
                    // already declares a HEALTHCHECK; this waits on its
                    // verdict.
                    sh '''
                        set -eu
                        echo "--- waiting for health"
                        for attempt in $(seq 1 60); do
                            state=$(docker inspect --format='{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo missing)
                            health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || echo none)

                            if [ "$health" = "healthy" ]; then
                                echo "healthy after ${attempt}s"
                                exit 0
                            fi

                            if [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
                                echo "container stopped on its own (state=$state)" >&2
                                break
                            fi

                            sleep 1
                        done

                        echo "service did not become healthy (state=${state:-?} health=${health:-?})" >&2
                        echo "--- last health probe ---" >&2
                        docker inspect --format='{{if .State.Health}}{{range .State.Health.Log}}{{.Output}}{{end}}{{end}}' "$CONTAINER" >&2 || true
                        echo "--- container logs ---" >&2
                        docker logs --tail 100 "$CONTAINER" >&2 || true
                        exit 1
                    '''

                    // Run inside the container, over its own loopback, for
                    // the same reason the health check reads Docker: the agent
                    // cannot be assumed to reach the published port. The
                    // service's own SECRET_KEY signs the token, so the download
                    // is verified end to end without submitting the access form
                    // — a form submission would write a fake person into the
                    // PDPA-governed table on every single deploy.
                    sh '''
                        set -eu
                        docker exec "$CONTAINER" python3 scripts/smoke_check.py
                    '''

                    // The only check that exercises nginx rather than the
                    // application alone — and the only one that must never fail
                    // the build. nginx runs on the host, outside anything this
                    // pipeline deploys, and `post { failure }` rolls the
                    // container back: a proxy that is merely misconfigured
                    // would otherwise revert a container that is working.
                    // A bad answer marks the build unstable and says why.
                    script {
                        // No `|| echo`: curl already prints 000 on a failed
                        // connection, so appending a word produced the
                        // uninterpretable "000unreachable" and sent this step
                        // down the failure branch.
                        def code = sh(
                            script: """set +e
curl -s -o /dev/null -w '%{http_code}' --max-time 10 "\$PUBLIC_URL/api/health"
exit 0""",
                            returnStdout: true
                        ).trim()

                        echo "--- through nginx"
                        if (code == "200") {
                            echo "    nginx serves the app at ${env.PUBLIC_URL}"
                        } else if (code == "000" || code == "") {
                            echo "    skipped: this agent cannot reach ${env.PUBLIC_URL}."
                            echo "    Check the proxy by hand once:"
                            echo "      curl -s https://<host>/dataset/api/health"
                        } else {
                            unstable("nginx answered ${code} for /dataset/api/health. " +
                                     "The container is healthy and the deploy stands; " +
                                     "this points at the host nginx config, not at the release.")
                        }
                    }
                }
            }
            post {
                failure {
                    script {
                        if (env.PREVIOUS_IMAGE && env.PREVIOUS_IMAGE != 'none') {
                            echo "Rolling back to ${env.PREVIOUS_IMAGE}"
                            withCredentials([file(
                                credentialsId: 'NORA_DATASET_ENV_PRODUCTION',
                                variable: 'ENV_FILE'
                            )]) {
                                sh '''
                                    set -eu
                                    cp "$ENV_FILE" .env.rollback
                                    chmod 600 .env.rollback
                                    IMAGE="$PREVIOUS_IMAGE" \
                                        docker compose --env-file .env.rollback \
                                            -f "$COMPOSE_FILE" up -d --force-recreate "$SERVICE" || true
                                '''
                            }
                        } else {
                            echo 'No previous image recorded, nothing to roll back to.'
                        }
                    }
                    sh '''
                        echo "=== container logs ==="
                        docker logs --tail 200 "$CONTAINER" 2>&1 || true
                    '''
                }
                success {
                    sh 'docker ps --format "table {{.Names}}\t{{.Status}}" | grep "$CONTAINER" || true'
                }
                always {
                    // The env file holds SECRET_KEY; it must not survive the build.
                    sh 'rm -f .env.production .env.rollback'
                    sh 'docker logout "$REGISTRY_URL" || true'
                    // Images only. `docker volume prune` would reach past this
                    // project and delete volumes belonging to other services
                    // on the same host.
                    sh 'docker image prune -f --filter "until=168h" || true'
                }
            }
        }
    }
}
