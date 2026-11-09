\# 🚀 Automated Flask CI/CD Pipeline on AWS



A hands-on DevOps project demonstrating automated testing, Docker containerization, continuous integration and deployment, and cloud hosting using AWS.



\*\*Live Application:\*\* \[https://rafaz-devops.duckdns.org](https://rafaz-devops.duckdns.org)



\*\*GitHub Repository:\*\* \[devops-project](https://github.com/mahammadrafaz/devops-project)



\## 📌 Project Overview



This project implements an automated CI/CD pipeline for a Python Flask application.



Whenever code is pushed to the `main` branch, GitHub Actions automatically runs tests, builds a Docker image, publishes it to Docker Hub, and deploys the updated application to an AWS EC2 instance using AWS Systems Manager.



Nginx acts as a reverse proxy, while HTTPS is configured using a free Let's Encrypt SSL certificate.



\## 🏗️ Architecture


![DevOps CI/CD Architecture](docs/devops_ci_cd_architecture.png)



```text

Developer

&#x20;   |

&#x20;   | Git Push

&#x20;   v

GitHub Repository

&#x20;   |

&#x20;   v

GitHub Actions

&#x20;   |

&#x20;   +---- Run Automated Tests (Pytest)

&#x20;   |

&#x20;   +---- Build Docker Image

&#x20;   |

&#x20;   +---- Push Image to Docker Hub

&#x20;   |

&#x20;   v

AWS OIDC Authentication

&#x20;   |

&#x20;   v

AWS Systems Manager (SSM)

&#x20;   |

&#x20;   v

AWS EC2 Instance

&#x20;   |

&#x20;   v

Nginx Reverse Proxy

&#x20;   |

&#x20;   v

Docker Container

&#x20;   |

&#x20;   v

Flask Application

```



\## 🛠️ Technologies Used



| Technology | Purpose |

|---|---|

| Python | Application development |

| Flask | Web framework |

| Pytest | Automated testing |

| Docker | Application containerization |

| Docker Hub | Container image registry |

| Git \& GitHub | Version control |

| GitHub Actions | CI/CD automation |

| AWS EC2 | Cloud hosting |

| AWS IAM OIDC | Secure GitHub-to-AWS authentication |

| AWS Systems Manager | Remote deployment without SSH |

| Nginx | Reverse proxy |

| DuckDNS | Free hostname |

| Let's Encrypt | Free SSL certificate |

| Certbot | SSL certificate management |



\## ⚙️ CI/CD Workflow



The pipeline follows these steps:



1\. Developer pushes code to the `main` branch.

2\. GitHub Actions checks out the repository.

3\. Python dependencies are installed.

4\. Pytest executes automated tests.

5\. Docker builds the application image.

6\. Docker image is pushed to Docker Hub.

7\. GitHub Actions authenticates with AWS using OIDC.

8\. AWS Systems Manager sends the deployment command to EC2.

9\. EC2 pulls the latest image and replaces the running container.

10\. A health check verifies the deployment.



\## 🔐 Security Implementation



\- AWS credentials are not stored as long-term access keys in GitHub.

\- GitHub Actions uses OIDC to assume an IAM deployment role.

\- AWS Systems Manager is used instead of SSH.

\- EC2 security group exposes HTTP (80) and HTTPS (443).

\- Flask's internal application port (5000) is not publicly exposed.

\- HTTPS is enabled using Let's Encrypt.



\## 🌐 Live Application



\*\*Homepage:\*\* https://rafaz-devops.duckdns.org



\*\*Health Check:\*\* https://rafaz-devops.duckdns.org/health



Expected health check response:



```json

{

&#x20; "status": "OK"

}

```



\## 📂 Project Structure



```text

devops-project/

│

├── .github/

│   └── workflows/

│       └── ci.yml

│

├── app.py

├── dockerfile

├── requirements.txt

├── test\_app.py

└── README.md

```



\## 💻 Run Locally



\### 1. Clone the repository



```bash

git clone https://github.com/mahammadrafaz/devops-project.git

cd devops-project

```



\### 2. Install dependencies



```bash

pip install -r requirements.txt

```



\### 3. Run the Flask application



```bash

python app.py

```



Open:



```text

http://localhost:5000

```



\### 4. Run automated tests



```bash

pytest -v

```



\## 🐳 Run Using Docker



\### Build the Docker image



```bash

docker build -f dockerfile -t devops-project .

```



\### Run the container



```bash

docker run -d -p 5000:5000 --name devops-flask devops-project

```



Open:



```text

http://localhost:5000

```



\## 🔄 Deployment



Deployment is automated through GitHub Actions.



To deploy an update:



```bash

git add .

git commit -m "Update application"

git push origin main

```



GitHub Actions automatically handles testing, Docker image publishing, and EC2 deployment.



\## 🎯 Key Learning Outcomes



\- Understanding CI/CD pipeline implementation.

\- Automating application testing.

\- Building and publishing Docker images.

\- Deploying applications on AWS EC2.

\- Configuring GitHub OIDC authentication with AWS IAM.

\- Using AWS Systems Manager for automated deployments.

\- Configuring Nginx as a reverse proxy.

\- Enabling HTTPS with Let's Encrypt.

\- Implementing health checks and automated SSL renewal.



\## 👨‍💻 Author



\*\*Mahammad Rafaz\*\*



Computer Science Engineering Student



GitHub: \[@mahammadrafaz](https://github.com/mahammadrafaz)

