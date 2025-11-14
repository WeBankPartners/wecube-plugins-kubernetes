#!/bin/bash
# HTTPS 私有仓库连接测试脚本

set -e

REGISTRY_HOST="${REGISTRY_HOST:-106.52.160.142}"
REGISTRY_USERNAME="${REGISTRY_USERNAME:-***REMOVED***}"
REGISTRY_PASSWORD="${REGISTRY_PASSWORD:-***REMOVED***@123}"

echo "=========================================="
echo "Testing HTTPS Registry Connection"
echo "=========================================="
echo "Host: $REGISTRY_HOST"
echo ""

# 测试常见端口
PORTS=(8443 443 8082 8081 5000)

for PORT in "${PORTS[@]}"; do
    echo "----------------------------------------"
    echo "Testing port $PORT..."
    echo "----------------------------------------"
    
    # 测试 HTTPS
    echo "1. Testing HTTPS connection..."
    if curl -k -s --connect-timeout 5 "https://${REGISTRY_HOST}:${PORT}/v2/" > /dev/null 2>&1; then
        echo "✓ HTTPS port $PORT is accessible!"
        
        # 测试认证
        echo "2. Testing authentication..."
        RESPONSE=$(curl -k -s -u "${REGISTRY_USERNAME}:${REGISTRY_PASSWORD}" "https://${REGISTRY_HOST}:${PORT}/v2/")
        
        if echo "$RESPONSE" | grep -q "Docker-Distribution-Api-Version\|errors"; then
            echo "✓ Authentication successful!"
            echo ""
            echo "=========================================="
            echo "✓✓✓ Found working HTTPS registry! ✓✓✓"
            echo "=========================================="
            echo "Registry: ${REGISTRY_HOST}:${PORT}"
            echo "Protocol: HTTPS"
            echo ""
            echo "Update your build.sh with:"
            echo "  PRIVATE_REGISTRY=\"${REGISTRY_HOST}:${PORT}\""
            echo ""
            
            # 测试证书
            echo "3. Checking SSL certificate..."
            openssl s_client -showcerts -connect "${REGISTRY_HOST}:${PORT}" </dev/null 2>&1 | \
                grep -E "subject=|issuer=" | head -2
            
            exit 0
        else
            echo "✗ Authentication failed"
        fi
    else
        echo "✗ Port $PORT not accessible via HTTPS"
    fi
    
    # 测试 HTTP（作为备选）
    echo "3. Testing HTTP connection (fallback)..."
    if curl -s --connect-timeout 5 "http://${REGISTRY_HOST}:${PORT}/v2/" > /dev/null 2>&1; then
        echo "⚠ Port $PORT is accessible via HTTP (not HTTPS)"
        echo "  If you want to use HTTP, you need to configure insecure-registries"
    fi
    
    echo ""
done

echo "=========================================="
echo "✗ No working HTTPS registry found"
echo "=========================================="
echo ""
echo "Please check:"
echo "1. Is Nexus running?"
echo "2. Is HTTPS configured in Nexus?"
echo "3. What is the correct HTTPS port?"
echo "4. Is the port open in firewall?"
echo ""
echo "You can manually test with:"
echo "  curl -k https://${REGISTRY_HOST}:YOUR_PORT/v2/"
echo ""

exit 1

