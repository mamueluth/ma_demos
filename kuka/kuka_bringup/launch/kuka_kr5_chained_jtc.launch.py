# Copyright 2023 Stogl Robotics Consulting UG (haftungsbeschränkt)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.substitutions import (
    Command,
    FindExecutable,
    LaunchConfiguration,
    PathJoinSubstitution,
)

from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def create_nodes_to_launch(context, *args, **kwargs):
    # initialize arguments
    prefix = LaunchConfiguration("prefix")
    use_mock_hardware = LaunchConfiguration("use_mock_hardware")
    activate_controller = LaunchConfiguration("activate_controller").perform(context)
    control_node = LaunchConfiguration("control_node")
    listen_ip_address = LaunchConfiguration("listen_ip_address")
    listen_port = LaunchConfiguration("listen_port")
    log_level_driver = LaunchConfiguration("log_level_driver")
    log_level_all = LaunchConfiguration("log_level_all")

    robot_description_content = Command(
        [
            PathJoinSubstitution([FindExecutable(name="xacro")]),
            " ",
            PathJoinSubstitution(
                [
                    FindPackageShare("kuka_ros2_control_support"),
                    "urdf",
                    "common_kuka.xacro",
                ]
            ),
            " ",
            "prefix:=",
            prefix,
            " ",
            "use_mock_hardware:=",
            use_mock_hardware,
            " ",
            "controllers_file:=kuka_6dof_controllers.yaml",
            " ",
            "robot_description_package:=kuka_kr5_support",
            " ",
            "robot_description_macro_file:=kr5_arc_macro.xacro",
            " ",
            "robot_name:=kuka_kr5_arc",
            " ",
            "listen_ip_address:=",
            listen_ip_address,
            " ",
            "listen_port:=",
            listen_port,
            " ",
        ]
    )

    robot_description = {"robot_description": robot_description_content}

    robot_controllers = PathJoinSubstitution(
        [
            FindPackageShare("kuka_bringup"),
            "controller_config",
            "kuka_6dof_controllers.yaml",
        ]
    )

    control_node = Node(
        package="kuka_ros2_control_support",
        executable=control_node,
        output="both",
        arguments=[
            "--ros-args",
            "--log-level",
            ["KukaSystemPositionOnlyHardware:=", log_level_driver],
            "--ros-args",
            "--log-level",
            ["controller_manager:=", log_level_driver],
            "--ros-args",
            "--log-level",
            log_level_all,
        ],
        parameters=[robot_description, robot_controllers],
    )

    robot_state_pub_node = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        parameters=[robot_description],
        output="both",
    )

    joint_state_broadcaster_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=[
            "joint_state_broadcaster",
            "--controller-manager",
            "/controller_manager",
        ],
    )

    controllers_to_spawn = []

    if activate_controller == "jtc":
        jtc_spawner = Node(
            package="controller_manager",
            executable="spawner",
            arguments=["position_trajectory_controller", "-c", "/controller_manager"],
        )

        delay_jtc_spawner_after_joint_state_broadcaster_spawner = RegisterEventHandler(
            event_handler=OnProcessExit(
                target_action=joint_state_broadcaster_spawner,
                on_exit=[jtc_spawner],
            )
        )
        controllers_to_spawn.append(
            delay_jtc_spawner_after_joint_state_broadcaster_spawner
        )
    elif activate_controller == "fpc":
        fpc_spawner = Node(
            package="controller_manager",
            executable="spawner",
            arguments=["forward_position_controller", "-c", "/controller_manager"],
        )

        delay_fpc_spawner_after_joint_state_broadcaster_spawner = RegisterEventHandler(
            event_handler=OnProcessExit(
                target_action=joint_state_broadcaster_spawner,
                on_exit=[fpc_spawner],
            )
        )
        controllers_to_spawn.append(
            delay_fpc_spawner_after_joint_state_broadcaster_spawner
        )
    elif activate_controller == "fpc_jtc_chain":
        # First load forward position controller (forward command controller with only position interface)
        # Execution of controllers depends on loading order
        # we want forward position controller to be executed before jtc since our chain looks like this:
        # ForwardCommandController->JointTrajectoryController->HW
        load_fpc = Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "fpc_jtc_chain_controller",
                "-c",
                "/controller_manager",
                "--load-only",
            ],
        )
        dealy_load_fpc_after_joint_state_broadcaster_spawner = RegisterEventHandler(
            event_handler=OnProcessExit(
                target_action=joint_state_broadcaster_spawner,
                on_exit=[load_fpc],
            )
        )
        controllers_to_spawn.append(
            dealy_load_fpc_after_joint_state_broadcaster_spawner
        )

        # Load chainable jtc and activate jtc. Activation needs to be done in the chain up
        # starting from HW site
        chained_jtc_spawner = Node(
            package="controller_manager",
            executable="spawner",
            arguments=["position_trajectory_controller", "-c", "/controller_manager"],
        )

        delay_chained_jtc_spawner_after_load_fpc = RegisterEventHandler(
            event_handler=OnProcessExit(
                target_action=load_fpc,
                on_exit=[chained_jtc_spawner],
            )
        )
        controllers_to_spawn.append(delay_chained_jtc_spawner_after_load_fpc)
    else:
        # Don't activate any controllers
        pass

    rviz_config_file = PathJoinSubstitution(
        [FindPackageShare("kuka_resources"), "config", "view_robot.rviz"]
    )

    rviz_node = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2",
        output="log",
        arguments=["-d", rviz_config_file],
    )

    delay_rviz_after_joint_state_broadcaster_spawner = RegisterEventHandler(
        event_handler=OnProcessExit(
            target_action=joint_state_broadcaster_spawner,
            on_exit=[rviz_node],
        )
    )

    nodes = [
        control_node,
        robot_state_pub_node,
        joint_state_broadcaster_spawner,
        delay_rviz_after_joint_state_broadcaster_spawner,
    ] + controllers_to_spawn

    return nodes


def generate_launch_description():
    declared_arguments = []

    declared_arguments.append(
        DeclareLaunchArgument(
            "prefix",
            default_value="",
            description="Prefix of the joint names, useful for \
        multi-robot setup. If changed than also joint names in the controllers' configuration \
        have to be updated.",
        )
    )
    declared_arguments.append(
        DeclareLaunchArgument(
            "use_mock_hardware",
            default_value="false",
            description="Start robot with fake hardware mirroring command to its states.",
        )
    )
    declared_arguments.append(
        DeclareLaunchArgument(
            "activate_controller",
            default_value="jtc",
            description="Set which controller gets activated by default",
            choices=["jtc", "fpc", "fpc_jtc_chain", "non"],
        )
    )
    declared_arguments.append(
        DeclareLaunchArgument(
            "listen_ip_address",
            default_value="172.20.19.101",
            description="The ip address on of your device on which is listend.",
        )
    )
    declared_arguments.append(
        DeclareLaunchArgument(
            "listen_port",
            default_value="49152",
            description="The port on which is listend.",
        )
    )
    declared_arguments.append(
        DeclareLaunchArgument(
            "log_level_driver",
            default_value="info",
            description="Set the logging level of the loggers of all started nodes.",
            choices=[
                "debug",
                "DEBUG",
                "info",
                "INFO",
                "warn",
                "WARN",
                "error",
                "ERROR",
                "fatal",
                "FATAL",
            ],
        )
    )
    declared_arguments.append(
        DeclareLaunchArgument(
            "log_level_all",
            default_value="info",
            description="Set the logging level of the loggers of all started nodes.",
            choices=[
                "debug",
                "DEBUG",
                "info",
                "INFO",
                "warn",
                "WARN",
                "error",
                "ERROR",
                "fatal",
                "FATAL",
            ],
        )
    )
    declared_arguments.append(
        DeclareLaunchArgument(
            "control_node",
            default_value="ros2_control_node_max_update_rate",
            description="Change the control node which is used.",
            choices=[
                "ros2_control_node",
                "ros2_control_node_steady_clock",
                "ros2_control_node_max_update_rate",
                "ros2_control_node_max_update_rate_sc",
                "ros2_control_node_fixed_period",
                "ros2_control_node_fixed_period_sc",
            ],
        )
    )

    return LaunchDescription(
        declared_arguments + [OpaqueFunction(function=create_nodes_to_launch)]
    )
