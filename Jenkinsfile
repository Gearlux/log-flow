pipeline {
    agent any

    environment {
        // Local virtual environment within the Jenkins workspace for portability
        VENV_PATH = "${WORKSPACE}/.venv"
        VENV_BIN = "${VENV_PATH}/bin"
    }

    stages {
        stage('Initialize') {
            steps {
                echo 'Creating Isolated Virtual Environment...'
                sh "python3 -m venv ${VENV_PATH}"
                
                echo 'Installing Dependencies in Editable Mode...'
                sh "${VENV_BIN}/pip install --upgrade pip"
                sh "${VENV_BIN}/pip install -e .[dev]"
            }
        }

        stage('Linting') {
            parallel {
                stage('Black') {
                    steps {
                        sh "${VENV_BIN}/black --check logflow tests examples"
                    }
                }
                stage('Isort') {
                    steps {
                        sh "${VENV_BIN}/isort --check-only logflow tests examples"
                    }
                }
                stage('Flake8') {
                    steps {
                        // Generate flake8 output in a format that can be converted to JUnit XML
                        sh "${VENV_BIN}/flake8 logflow tests examples --tee --output-file=flake8.txt"
                        // Convert flake8.txt to JUnit XML for Jenkins reporting
                        sh "${VENV_BIN}/flake8_junit flake8.txt flake8-report.xml"
                    }
                    post {
                        always {
                            junit 'flake8-report.xml'
                        }
                    }
                }
            }
        }

        stage('Type Check') {
            steps {
                sh "${VENV_BIN}/mypy logflow tests examples"
            }
        }

        stage('Unit Tests') {
            steps {
                sh "${VENV_BIN}/pytest tests"
            }
        }
    }

    post {
        always {
            echo 'LogFlow Pipeline Complete.'
        }
        success {
            echo 'Project is healthy and ready for publication.'
        }
        failure {
            echo 'Build failed. Please check linting or test failures.'
        }
    }
}
