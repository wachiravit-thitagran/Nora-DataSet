// Deploys the dataset web service to ainora-agent.
//
// The image is built by GitHub Actions (.github/workflows/ci.yml) and pushed
// to GitHub Container Registry; this pipeline only pulls a tag and swaps the
// running container. Bundle files are never touched here — they live on the
// server's data volume and are updated out of band with rsync.

pipeline {
    agent { label 'ainora-agent' }

    parameters {
        string(
            name: 'IMAGE_TAG',
            defaultValue: 'latest',
            description: 'Image tag to deploy (GitHub short SHA, or "latest")'
        )
        booleanParam(
            name: 'RUN_SMOKE_TESTS',
            defaultValue: true,
            description: 'Verify the gate actually blocks direct file access after deploy'
        )
    }

    environment {
        REGISTRY     = 'ghcr.io'
        // Must be lowercase: ghcr.io rejects uppercase in image paths.
        IMAGE_REPO   = 'wachiravit-thitagran/dataset_web'
        COMPOSE_FILE = '/srv/ainora/dataset-web/docker-compose.yml'
        SERVICE      = 'dataset-web'
        // The container, reached directly (bypasses nginx).
        BASE_URL     = 'http://127.0.0.1:10095'
        // The same service as the public sees it, through the host nginx.
        PUBLIC_URL   = 'http://127.0.0.1/dataset'
    }

    options {
        timeout(time: 15, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }

    stages {

        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Pull image') {
            steps {
                // GitHub username + a classic PAT with read:packages scope,
                // stored in Jenkins as a username/password credential.
                withCredentials([usernamePassword(
                    credentialsId: 'ghcr-registry',
                    usernameVariable: 'REG_USER',
                    passwordVariable: 'REG_PASS'
                )]) {
                    sh '''
                        set -eu
                        echo "$REG_PASS" | docker login -u "$REG_USER" --password-stdin "$REGISTRY"
                        docker pull "$REGISTRY/$IMAGE_REPO:$IMAGE_TAG"
                    '''
                }
            }
        }

        stage('Record current image') {
            steps {
                script {
                    // Captured so the rollback stage has something concrete to
                    // return to rather than guessing at "the previous one".
                    env.PREVIOUS_IMAGE = sh(
                        script: "docker inspect --format='{{.Config.Image}}' ainora-dataset-web 2>/dev/null || echo none",
                        returnStdout: true
                    ).trim()
                    echo "Current image: ${env.PREVIOUS_IMAGE}"
                }
            }
        }

        stage('Deploy') {
            steps {
                withCredentials([string(
                    credentialsId: 'nora-dataset-secret-key',
                    variable: 'SECRET_KEY'
                )]) {
                    sh '''
                        set -eu
                        export IMAGE="$REGISTRY/$IMAGE_REPO:$IMAGE_TAG"
                        mkdir -p /srv/ainora/dataset-db
                        docker compose -f "$COMPOSE_FILE" up -d --force-recreate "$SERVICE"
                    '''
                }
            }
        }

        stage('Health check') {
            steps {
                sh '''
                    set -eu
                    for attempt in $(seq 1 30); do
                        if curl -fsS "$BASE_URL/api/health" | grep -q '"ok"'; then
                            echo "healthy after ${attempt}s"
                            exit 0
                        fi
                        sleep 1
                    done
                    echo "service did not become healthy" >&2
                    docker logs --tail 100 ainora-dataset-web >&2
                    exit 1
                '''
            }
        }

        stage('Smoke tests') {
            when { expression { params.RUN_SMOKE_TESTS } }
            steps {
                // SECRET_KEY is needed to mint a download token for the
                // end-to-end check without going through the access form.
                withCredentials([string(
                    credentialsId: 'nora-dataset-secret-key',
                    variable: 'SECRET_KEY'
                )]) {
                sh '''
                    set -eu

                    echo "--- catalogue responds"
                    curl -fsS "$BASE_URL/api/catalog" > /dev/null

                    echo "--- download without a token is refused"
                    code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/download/keypoints")
                    [ "$code" = "403" ] || { echo "expected 403, got $code" >&2; exit 1; }

                    echo "--- forged token is refused"
                    code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/download/keypoints?t=aaa.bbb")
                    [ "$code" = "403" ] || { echo "expected 403, got $code" >&2; exit 1; }

                    # Everything below goes through the real nginx, so it also
                    # checks the proxy configuration, not just the app.

                    first=$(curl -fsS "$BASE_URL/api/catalog" \\
                        | python3 -c "import json,sys; \\
                            b=[x for x in json.load(sys.stdin)['manifest']['bundles'] if x.get('filename')]; \\
                            print(b[0]['id'] if b else '')")

                    if [ -z "$first" ]; then
                        echo "--- no bundle published yet, skipping download check"
                    else
                        echo "--- a real download returns the whole file"
                        # Mint the token from the secret rather than submitting
                        # the form: a form submission would write a fake person
                        # into the PDPA-governed table on every single deploy.
                        token=$(python3 scripts/mint_token.py --ttl 300)

                        expected=$(curl -fsS "$BASE_URL/api/catalog" \\
                            | python3 -c "import json,sys; \\
                                b=[x for x in json.load(sys.stdin)['manifest']['bundles'] if x.get('filename')]; \\
                                print(b[0]['bytes'])")

                        got=$(curl -s -o /dev/null -w '%{size_download}' \\
                            "$PUBLIC_URL/api/download/$first?t=$token")

                        [ "$got" = "$expected" ] || {
                            echo "download returned $got bytes, expected $expected" >&2
                            exit 1
                        }
                        echo "    served $got bytes as expected"
                    fi
                '''
                }
            }
        }
    }

    post {
        failure {
            script {
                if (env.PREVIOUS_IMAGE && env.PREVIOUS_IMAGE != 'none') {
                    echo "Rolling back to ${env.PREVIOUS_IMAGE}"
                    withCredentials([string(
                        credentialsId: 'nora-dataset-secret-key',
                        variable: 'SECRET_KEY'
                    )]) {
                        sh '''
                            set -eu
                            export IMAGE="$PREVIOUS_IMAGE"
                            docker compose -f "$COMPOSE_FILE" up -d --force-recreate "$SERVICE" || true
                        '''
                    }
                }
            }
        }
        always {
            sh 'docker image prune -f --filter "until=168h" || true'
        }
    }
}
